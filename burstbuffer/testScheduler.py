# docker run --rm --net host -u 501:20 -v /Users/jankopanski/master2/Burst-Buffer-Scheduling:/data oarteam/batsim:4.0.0 -s tcp://host.docker.internal:28000 -p platforms/dragonfly96.xml -w workloads/generated_two_nodes.json -r node_0,node_9,node_18,node_27,node_36,node_45,node_54,node_63,node_72,node_81,node_90,node_99:storage -e output/out --enable-dynamic-jobs --acknowledge-dynamic-jobs

from batsim.sched.scheduler import Scheduler
from batsim.sched.profiles import Profiles
from batsim.sched.job import Job
from batsim.sched.alloc import Allocation
from procset import ProcSet

from .storage import StorageResource, StorageAllocation


class TestScheduler(Scheduler):
    def __init__(self, options):
        super().__init__(options=options)
        # self._logger._logger.setLevel('WARNING')
        self._event_logger._logger.setLevel('WARNING')
        self._registration_finished = False

    def on_init(self):
        for storage_resource in self.machines['storage']:
            if storage_resource['name'] == 'pfs':
                self._pfs = StorageResource(
                    scheduler=self,
                    id=storage_resource["id"],
                    name=storage_resource["name"],
                    resources_list=self.resources
                )
            else:
                self._resources.add(StorageResource(
                    scheduler=self,
                    id=storage_resource["id"],
                    name=storage_resource["name"],
                    resources_list=self.resources
                ))

    def on_job_submission(self, job):
        if not job.is_dynamic_job:
            walltime = 3

            # About 0.4 s
            profile1 = Profiles.DataStaging(size=5*10**8)
            job.submit_sub_job(2, walltime, profile1)

            profile2 = Profiles.ParallelHomogeneous(cpu=2*10**9, com=0, bb=0)
            job.submit_sub_job(job.requested_resources, walltime, profile2)

            # Test for double submission of the same profile
            # profile3 = Profiles.ParallelHomogeneous(cpu=2 * 10 ** 9, com=0, bb=0)
            # job.submit_sub_job(job.requested_resources, walltime, profile2)

            # That much I/O is sent to every allocated compute node
            profile3 = Profiles.ParallelPFS(size_read=5*10**8, size_write=10**8)
            job.submit_sub_job(job.requested_resources, -1, profile3)

            for sub_job_description in job.sub_jobs_workload.jobs:
                batsim_job = self._batsim.jobs[sub_job_description.id]

                # Manually set sub_job as in BaseBatsimScheduler.onJobSubmission();
                sub_job = Job(
                    number=self._scheduler._next_job_number,
                    batsim_job=batsim_job,
                    scheduler=self,
                    jobs_list=self.jobs
                )
                self._scheduler._jobmap[batsim_job.id] = sub_job
                self._scheduler._next_job_number += 1

                self.jobs.add(sub_job)

                sub_job_description.job = sub_job
                sub_job._workload_description = job.sub_jobs_workload

    def on_job_completion(self, job):
        next_job: Job = job.parent_job.sub_jobs.runnable.first
        if next_job:
            new_allocation = Allocation(
                start_time=self.time,
                walltime=job.allocation.walltime - (self.time - job.allocation.start_time),
                resources=job.parent_job.assigned_compute_resources
            )
            if next_job.profile.type == Profiles.ParallelPFS.type:
                next_job._batsim_job.storage_mapping = {'pfs': self._pfs.id}
                new_allocation.add_resource(self._pfs)
            next_job.schedule(new_allocation)
        print('completed ', job.id)
        # job.allocation.remove_all_resources()
        # job.allocation.free()
        # job.free()
        # job.parent_job.reject()
        pass

    def on_end(self):
        pass

    def schedule(self):
        # TODO: add a flag to only once send the registration finished message
        if not self._registration_finished and self._batsim.no_more_static_jobs:
            print('end of static jobs')
            self.notify_registration_finished()
            self._registration_finished = True
        self.high_level_sub_job()
        # self.high_level_new_dynamic_job_registration()

    def high_level_sub_job(self):
        # Requires only --enable-dynamic-jobs
        for job in self.jobs.static_job.runnable:
            for sub_job in job.sub_jobs:
                assigned_compute_resources = \
                    self.resources.compute.find_sufficient_resources_for_job(job)
                assert assigned_compute_resources
                job.assigned_compute_resources = assigned_compute_resources
                self.schedule_data_staging(
                    sub_job, self._pfs, self.resources.special.first, job.requested_time)
                job.reject()
                break
                # job.change_state(Job.State.RUNNING)

    def high_level_new_dynamic_job_registration(self):
        # Requires --enable-dynamic-jobs --acknowledge-dynamic-jobs
        jobs = self.jobs.runnable
        for job in jobs:
            if job.id == 'w0!0':
                new_profile = Profiles.ParallelHomogeneous(cpu=10 ** 9, com=0, bb=0)
                self.register_dynamic_job(
                    1,
                    10,
                    new_profile,
                )
                self.notify_registration_finished()
            assigned_compute_resources = self.resources.compute.find_sufficient_resources_for_job(
                job)
            job.schedule(assigned_compute_resources)
            print('scheduled ', job.id)

        for dynamic_job in self.dynamic_workload.acknowledged_jobs:
            print('DYNAMIC ', dynamic_job.id)
        #     assigned_compute_resources = self.resources.compute.find_sufficient_resources_for_job(
        #         dynamic_job)
        #     dynamic_job.schedule(assigned_compute_resources)

    def schedule_data_staging(
            self,
            job: Job,
            source: StorageResource,
            destination: StorageResource,
            walltime=None
    ):
        allocation = StorageAllocation(
            start_time=self.time,
            walltime=walltime if walltime else -1,
            resources=[source, destination],
            job=job
        )
        allocation.allocate_all(self)
        job._allocation = allocation
        job._batsim_job.allocation = ProcSet(source.id, destination.id)
        job._batsim_job.storage_mapping = {
            'source': source.id,
            'destination': destination.id
        }
        self._batsim.execute_job(job._batsim_job)
