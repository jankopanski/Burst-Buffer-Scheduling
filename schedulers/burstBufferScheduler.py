from batsim.batsim import BatsimScheduler, Job
from procset import ProcSet
from itertools import islice
from tqdm import tqdm


BB_CAPACITY_GB = 256
BB_CAPACITY = BB_CAPACITY_GB * 10**9


class JobInfo:
    def __init__(self, job):
        self.job = job
        self.requires_bb = 'bb' in job.profile_dict and job.profile_dict['bb'] > 0

    def assign(self, burst_buffers):
        self.burst_buffers = burst_buffers  # map storage_id to nb_bytes
        self.num_bb = len(burst_buffers)
        self.bb_ready = 0


class BurstBufferScheduler(BatsimScheduler):
    def onAfterBatsimInit(self):
        self.sched_delay = 0

        self.compute_resources = ProcSet((0, self.bs.nb_compute_resources-1))
        self.pfs = next(res['id'] for res in self.bs.storage_resources.values() if res['name'] == 'pfs')
        self.storage_resources = {sid: BB_CAPACITY for sid, res in
                                  self.bs.storage_resources.items() if res['name'] != 'pfs'}
        self.storage_id_to_name = {id: res['name'] for id, res in self.bs.storage_resources.items()}

        self.jobs_info = {}  # map from job.id to job_info
        self.waiting_bb_jobs = []
        self.waiting_res_jobs = []
        self.num_jobs_submitted = 0
        self.num_jobs_completed = 0

        num_all_jobs = sum(len(workload) for workload in self.bs.profiles.values())
        self.pbar = tqdm(total=num_all_jobs, smoothing=0.5)

    def onJobSubmission(self, job):
        self.num_jobs_submitted += 1
        job_info = JobInfo(job)
        self.jobs_info[job.id] = job_info
        if job_info.requires_bb:
            self.waiting_bb_jobs.append(job.id)
            self.schedule_burst_buffers()
        else:
            self.waiting_res_jobs.append(job.id)
            self.schedule_resources()

    def onJobCompletion(self, job):
        org_job_id, job_type = self.get_job_type(job.id)
        job_info = self.jobs_info[org_job_id]

        if job_type == 'in':
            assert job.job_state == Job.State.COMPLETED_SUCCESSFULLY
            job_info.bb_ready += 1
            if job_info.bb_ready == job_info.num_bb:
                job_info.bb_ready = 0
                self.waiting_res_jobs.append(org_job_id)
                self.schedule_resources()

        elif job_type == 'org':
            if job.job_state == Job.State.COMPLETED_SUCCESSFULLY and job_info.requires_bb:
                stage_out_jobs = self.generate_stage_jobs(job_info, 'out')
                self.execute(stage_out_jobs)
            else:
                self.cleanup_job(org_job_id)
            self.compute_resources |= job.allocation
            self.incr_num_jobs_completed()
            self.schedule_resources()

        elif job_type == 'out':
            assert job.job_state == Job.State.COMPLETED_SUCCESSFULLY
            job_info.bb_ready += 1
            if job_info.bb_ready == job_info.num_bb:
                self.cleanup_job(org_job_id)
                self.schedule_burst_buffers()

        else:
            assert False

    def onSimulationEnds(self):
        self.pbar.close()

    def execute(self, scheduled_jobs):
        self.bs.consume_time(self.sched_delay)
        if len(scheduled_jobs) > 0:
            self.bs.execute_jobs(scheduled_jobs)

    def schedule_burst_buffers(self):
        scheduled_jobs = []
        reject_jobs = []
        new_waiting_bb_jobs = []

        for job_id in self.waiting_bb_jobs:
            job_info = self.jobs_info[job_id]
            nb_bytes = job_info.job.profile_dict['bb']

            if nb_bytes > len(self.storage_resources) * BB_CAPACITY:
                reject_jobs.append(job_info.job)
                self.incr_num_jobs_completed()
                continue

            burst_buffers = self.allocate_burst_buffers(nb_bytes)
            if not burst_buffers:
                new_waiting_bb_jobs.append(job_id)
                continue

            job_info.assign(burst_buffers)
            scheduled_jobs.extend(self.generate_stage_jobs(job_info, 'in'))

        self.waiting_bb_jobs = new_waiting_bb_jobs
        if reject_jobs:
            self.bs.reject_jobs(reject_jobs)
        self.execute(scheduled_jobs)

    def schedule_resources(self):
        scheduled_jobs = []
        new_waiting_res_jobs = []

        for job_id in self.waiting_res_jobs:
            job_info = self.jobs_info[job_id]
            job = job_info.job
            nb_res_req = job.requested_resources

            if nb_res_req > len(self.compute_resources):
                new_waiting_res_jobs.append(job_id)
                continue

            job_alloc = ProcSet(*islice(self.compute_resources, nb_res_req))
            job.allocation = job_alloc
            scheduled_jobs.append(job)
            self.compute_resources -= job_alloc

        self.waiting_res_jobs = new_waiting_res_jobs
        self.execute(scheduled_jobs)

    def allocate_burst_buffers(self, nb_bytes):
        assert nb_bytes > 0
        assigned_storages = {}
        for storage_id, capacity in self.storage_resources.items():
            if 0 < capacity < nb_bytes:
                assigned_storages[storage_id] = capacity
                nb_bytes -= capacity
            elif capacity >= nb_bytes:
                assigned_storages[storage_id] = nb_bytes
                nb_bytes = 0
                break
        if nb_bytes == 0:
            assert assigned_storages
            for storage_id, capacity in assigned_storages.items():
                self.storage_resources[storage_id] -= capacity
            return assigned_storages
        return None

    def generate_stage_jobs(self, job_info, stage):
        assert stage in ['in', 'out']
        job = job_info.job
        register_profiles = {}
        register_jobs = []

        for storage_id, nb_bytes in job_info.burst_buffers.items():
            job_id = job.id + '_' + stage + '_' + str(storage_id)
            profile_id = job.profile + '_' + job_id
            storage = self.storage_id_to_name[storage_id]
            if stage == 'in':
                profile = {'type': 'data_staging', 'nb_bytes': nb_bytes, 'from': 'pfs', 'to': storage}
            else:
                profile = {'type': 'data_staging', 'nb_bytes': nb_bytes, 'from': storage, 'to': 'pfs'}
            register_profiles[profile_id] = profile
            stage_job = Job(id=job_id, subtime=0, walltime=-1, res=1, profile=profile_id, json_dict="")
            stage_job.allocation = ProcSet(storage_id, self.pfs)
            stage_job.storage_mapping = {'pfs': self.pfs, storage: storage_id}
            register_jobs.append(stage_job)
        self.bs.register_profiles(job.workload, register_profiles)

        for rj in register_jobs:
            self.bs.register_job(
                id=rj.id,
                res=rj.requested_resources,
                walltime=rj.requested_time,
                profile_name=rj.profile
            )
        return register_jobs

    def cleanup_job(self, job_id):
        if self.jobs_info[job_id].requires_bb:
            for storage_id, nb_bytes in self.jobs_info[job_id].burst_buffers.items():
                self.storage_resources[storage_id] += nb_bytes
        del self.jobs_info[job_id]

    def incr_num_jobs_completed(self):
        self.num_jobs_completed += 1
        self.pbar.update()
        if self.bs.no_more_static_jobs and self.num_jobs_completed >= self.num_jobs_submitted:
            assert self.num_jobs_completed == self.num_jobs_submitted
            self.bs.notify_registration_finished()

    @staticmethod
    def get_job_type(job_id):
        split = job_id.split('_')
        if len(split) == 1:
            return split[0], 'org'
        elif len(split) == 3:
            return split[0], split[1]
        assert False
