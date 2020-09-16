from typing import List, Dict
from enum import Enum

from batsim.batsim import Job as BatsimJob
from batsim.sched import Profiles, Allocation, ComputeResource, Job
from procset import ProcSet

from .alloc_only import AllocOnlyScheduler
from .storage import StorageResource, StorageAllocation
from .model import GFLOPS


class JobPhase(Enum):
    SUBMITTED = 1
    STAGE_IN = 2
    COMPUTE = 3
    CHECKPOINT = 4
    STAGE_OUT = 5
    COMPLETED = 6


class StaticJob(Job):
    """Job from a static workload"""
    phase: JobPhase
    assigned_compute_resources: List[ComputeResource]
    assigned_burst_buffers: Dict[ComputeResource, StorageResource]
    # Data staging jobs do not reserve compute resources. To ensure exclusiveness of assigned
    # compute resources additional temporary allocations must be created for the lifetime of
    # stage-in, stage-out jobs and finished ParallelPfs jobs. These allocations will not be
    # activated as they are not scheduled with any job to Batsim.
    inactive_allocations: List[Allocation]
    num_compute_phases: int
    compute_phase_size: int
    checkpoint_phase_size: int
    completed_compute_phases: int


class IOAwareScheduler(AllocOnlyScheduler):
    def __init__(self, options):
        super().__init__(options)
        self._num_completed_jobs = 0
        # TODO: Change _target_compute_phase_length and _checkpoint_phase_factor to parameters.
        self._target_compute_phase_length = 100 * GFLOPS
        self._checkpoint_phase_factor = 0.5

    def on_job_submission(self, static_job: StaticJob):
        assert not static_job.is_dynamic_job
        assert static_job.profile.type == Profiles.ParallelHomogeneous.type
        static_job.comment = static_job.profile.bb
        if not self._validate_job(static_job):
            self._increase_num_completed_jobs()
            return

        # TODO: real runtime type of static_job is job.Job.
        #  The type hint is set to StaticJob just for more convenient static type inference.
        #  Perhaps the following type casting would be helpful for runtime debugging.
        # job.__class__ = StaticJob

        static_job.inactive_allocations = []
        static_job.num_compute_phases = max(
            round(static_job.profile.cpu / self._target_compute_phase_length), 1)
        static_job.compute_phase_size = static_job.profile.cpu / static_job.num_compute_phases
        static_job.checkpoint_phase_size = int(
            self._checkpoint_phase_factor * static_job.profile.bb)
        static_job.completed_compute_phases = 0
        static_job.phase = JobPhase.SUBMITTED

    def on_job_completion(self, job: Job):
        assert job.is_dynamic_job
        static_job: StaticJob = job.parent_job
        assert not static_job.sub_jobs.open

        if job.profile.type == Profiles.DataStaging.type:
            # TODO: do not check data drain jobs
            if len(static_job.sub_jobs.completed) == len(static_job.sub_jobs.submitted):
                assert job.requested_time > 0, 'Data drain job should not meet the above condition'
                IOAwareScheduler._free_inactive_allocations(static_job)
                if static_job.phase == JobPhase.STAGE_IN:
                    if all(stage_in_job.success for stage_in_job in static_job.sub_jobs):
                        # All stage-in jobs finished successfully
                        self._init_compute_phase(static_job, self._remaining_walltime(job))
                    else:
                        # All stage-in jobs finished, but some run out of time
                        self._complete_job(static_job)
                elif static_job.phase == JobPhase.STAGE_OUT:
                    # All stage-out jobs finished
                    self._complete_job(static_job)
                else:
                    assert False

        elif job.profile.type == Profiles.ParallelHomogeneous.type:
            assert static_job.phase == JobPhase.COMPUTE
            static_job.completed_compute_phases += 1
            if not job.success:
                self._complete_job(static_job)
            elif static_job.completed_compute_phases == static_job.num_compute_phases:
                self._init_stage_out_phase(static_job, self._remaining_walltime(job))
            else:
                self._init_checkpoint_phase(static_job, self._remaining_walltime(job))

        elif job.profile.type == Profiles.ParallelPFS.type:
            assert static_job.phase == JobPhase.CHECKPOINT
            if len(static_job.sub_jobs.completed) == len(static_job.sub_jobs.submitted):
                IOAwareScheduler._free_inactive_allocations(static_job)
                # Schedule next compute phase
                self._init_compute_phase(static_job, self._remaining_walltime(job))
                self._init_data_drain(static_job)
            else:
                static_job.inactive_allocations.append(Allocation(
                    start_time=self.time,
                    walltime=-1,
                    resources=job.allocation.resources
                ))

        else:
            assert False
        assert not static_job.sub_jobs.open
        self._progress_bar.update(0)

    def _remaining_walltime(self, sub_job: Job):
        assert sub_job.completed
        new_walltime = sub_job.allocation.walltime - (self.time - sub_job.allocation.start_time)
        assert new_walltime > 0
        return new_walltime

    def _complete_job(self, static_job: StaticJob):
        assert not static_job.inactive_allocations
        self._free_burst_buffers(static_job)
        static_job.phase = JobPhase.COMPLETED
        self._increase_num_completed_jobs()

    def _increase_num_completed_jobs(self):
        self._num_completed_jobs += 1
        self._progress_bar.update()
        # Only static jobs count
        if self._num_completed_jobs >= self._num_all_jobs:
            assert self._batsim.no_more_static_jobs
            self.notify_registration_finished()

    def _init_compute_phase(self, static_job: StaticJob, walltime: float):
        assert not static_job.inactive_allocations
        # New job registration
        # This profile registration requires --enable-profile-reuse Batsim command line flag.
        parallel_homogeneous_profile = Profiles.ParallelHomogeneous(
            cpu=static_job.compute_phase_size,
            com=static_job.profile.com,
        )
        static_job.submit_sub_job(static_job.requested_resources, walltime,
                                  parallel_homogeneous_profile)
        self._create_sub_job_objects(static_job)

        assert len(static_job.sub_jobs.runnable) == 1
        # New job schedule
        next_job: Job = static_job.sub_jobs.last
        assert next_job.profile.type == Profiles.ParallelHomogeneous.type
        new_allocation = Allocation(
            start_time=self.time,
            walltime=walltime,
            resources=static_job.assigned_compute_resources
        )
        next_job.schedule(new_allocation)
        static_job.phase = JobPhase.COMPUTE

    def _init_checkpoint_phase(self, static_job: StaticJob, walltime: float):
        assert not static_job.inactive_allocations
        parallel_pfs_profile = Profiles.ParallelPFS(
            size_read=0,
            size_write=static_job.checkpoint_phase_size,
            storage='burstbuffer'
        )
        for _ in range(len(static_job.assigned_burst_buffers)):
            static_job.submit_sub_job(1, walltime, parallel_pfs_profile)
        self._create_sub_job_objects(static_job)

        assert len(static_job.sub_jobs.runnable) == len(static_job.assigned_burst_buffers)
        for parallel_pfs_job, (compute_resource, burst_buffer) in zip(
                static_job.sub_jobs.runnable, static_job.assigned_burst_buffers.items()):
            new_allocation = Allocation(
                start_time=self.time,
                walltime=walltime,
                resources=[compute_resource, burst_buffer]
            )
            parallel_pfs_job._batsim_job.storage_mapping = {'burstbuffer': burst_buffer.id}
            parallel_pfs_job.schedule(new_allocation)
        static_job.phase = JobPhase.CHECKPOINT

    def _init_stage_in_phase(self, static_job: StaticJob):
        self._init_data_staging(static_job, static_job.requested_time, static_job.profile.bb, False)
        static_job.inactive_allocations.append(Allocation(
            start_time=self.time,
            walltime=-1,
            resources=static_job.assigned_compute_resources
        ))
        static_job.phase = JobPhase.STAGE_IN
        assert len(static_job.sub_jobs.running) == len(static_job.assigned_burst_buffers)

    def _init_data_drain(self, static_job: StaticJob):
        # Trigger draining IO traffic from burst buffers to PFS
        # This simulates moving a checkpoint from burst buffers to PFS
        self._init_data_staging(static_job, -1, static_job.checkpoint_phase_size, True)

    def _init_stage_out_phase(self, static_job: StaticJob, walltime: float):
        self._init_data_staging(static_job, walltime, static_job.profile.bb, True)
        static_job.inactive_allocations.append(Allocation(
            start_time=self.time,
            walltime=-1,
            resources=static_job.assigned_compute_resources
        ))
        static_job.phase = JobPhase.STAGE_OUT

    def _init_data_staging(
            self,
            static_job: StaticJob,
            walltime: float,
            size: int,
            direction_to_pfs=True
    ):
        # Register data staging jobs
        data_staging_profile = Profiles.DataStaging(size)
        for _ in range(static_job.requested_resources):
            static_job.submit_sub_job(2, walltime, data_staging_profile)
        self._create_sub_job_objects(static_job)

        # Schedule data staging jobs
        assert len(static_job.sub_jobs.runnable) == len(static_job.assigned_burst_buffers)
        for data_staging_job, burst_buffer in zip(
                static_job.sub_jobs.runnable, static_job.assigned_burst_buffers.values()):
            self._schedule_data_staging(
                job=data_staging_job,
                source=burst_buffer if direction_to_pfs else self._pfs,
                destination=self._pfs if direction_to_pfs else burst_buffer,
                walltime=walltime
            )

    def _schedule_data_staging(
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

        # Copy from the Job.schedule() method; job.py:569
        self.info(
            "Scheduled job ({job})",
            job=job,
            type="job_scheduled")
        job._scheduled = True
        job._start_time = self.time
        job._jobs_list.update_element(self)

    def schedule(self):
        jobs = self.jobs.static_job.runnable
        for job in jobs:
            assigned_compute_resources, assigned_burst_buffers = self._find_all_resources(job)
            if assigned_compute_resources and assigned_burst_buffers:
                self._schedule_job(job, assigned_compute_resources, assigned_burst_buffers)

    def _schedule_job(
            self,
            static_job: StaticJob,
            assigned_compute_resources: List[ComputeResource],
            assigned_burst_buffers: Dict[ComputeResource, StorageResource]
    ):
        assert assigned_compute_resources
        assert assigned_burst_buffers
        static_job.assigned_compute_resources = assigned_compute_resources
        static_job.assigned_burst_buffers = assigned_burst_buffers
        assert self._exclusive_compute_resources(static_job)

        self._allocate_burst_buffers(self.time, self.time + static_job.requested_time,
                                     assigned_burst_buffers, static_job)
        self._init_stage_in_phase(static_job)
        static_job.reject('Static job scheduled')
        assert not static_job.sub_jobs.open

    # TODO: could return Jobs object
    def _create_sub_job_objects(self, job: Job):
        """
        Creates high-level Job objects for submitted JobDescription of sub-jobs of the given job.
        Must be called after a sequence of job.submit_sub_job() calls if --acknowledge-dynamic-jobs
        flag is not specified for Batsim simulator.
        """
        assert job.parent_job is None
        for sub_job_description in job.sub_jobs_workload:
            if sub_job_description.job:
                continue
            batsim_job: BatsimJob = self._batsim.jobs[sub_job_description.id]

            # Manually set sub_job; based on BaseBatsimScheduler.onJobSubmission()
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

    def _exclusive_compute_resources(self, static_job: StaticJob) -> bool:
        """
        Checks if newly scheduled job has exclusive compute resources with previously scheduled
        jobs. Must be called before static_job.reject().
        """
        assert not static_job.rejected
        previously_assigned_compute_resources = set()
        for job in self.jobs.static_job.rejected:
            if job.phase != JobPhase.COMPLETED:
                previously_assigned_compute_resources.update(job.assigned_compute_resources)
        return previously_assigned_compute_resources.isdisjoint(
            static_job.assigned_compute_resources)

    @staticmethod
    def _free_inactive_allocations(static_job: StaticJob):
        for allocation in static_job.inactive_allocations:
            allocation.remove_all_resources()
        static_job.inactive_allocations.clear()
