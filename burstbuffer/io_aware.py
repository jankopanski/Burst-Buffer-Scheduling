from typing import List, Dict
from enum import Enum

from batsim.batsim import Job as BatsimJob
from batsim.sched import Profiles, Allocation, ComputeResource, Job
from procset import ProcSet

from .alloc_only import AllocOnlyScheduler
from .storage import StorageResource, StorageAllocation


class JobPhase(Enum):
    SUBMITTED = 1
    STAGE_IN = 2
    RUNNING = 3
    STAGE_OUT = 4
    COMPLETED = 5


class StaticJob(Job):
    """Job from a static workload"""
    phase: JobPhase
    assigned_compute_resources: List[ComputeResource]
    assigned_burst_buffers: Dict[ComputeResource, StorageResource]


class IOAwareScheduler(AllocOnlyScheduler):
    def __init__(self, options):
        super().__init__(options)
        self._num_completed_jobs = 0

    def on_job_submission(self, job: StaticJob):
        assert not job.is_dynamic_job
        assert job.profile.type == Profiles.ParallelHomogeneous.type
        if not self._validate_job(job):
            self._increase_num_completed_jobs()
            return
        # job.__class__ = StaticJob

        stage_in_profile = Profiles.DataStaging(size=job.profile.bb)
        for _ in range(job.requested_resources):
            job.submit_sub_job(2, job.requested_time, stage_in_profile)
        self._create_sub_job_objects(job)
        job.phase = JobPhase.SUBMITTED
        # job.stage_in_submitted = len(job.sub_jobs_workload.jobs)
        # job.stage_in_completed = 0

    def on_job_completion(self, job: Job):
        assert job.is_dynamic_job
        static_job: StaticJob = job.parent_job

        if job.profile.type == Profiles.DataStaging.type:
            if len(static_job.sub_jobs.completed) == len(static_job.sub_jobs.submitted):
                # All stage-in jobs finished
                if static_job.phase == JobPhase.STAGE_IN:
                    if not all(stage_in_job.success for stage_in_job in static_job.sub_jobs):
                        self._increase_num_completed_jobs()
                        self._free_burst_buffers(static_job)
                        static_job.phase = JobPhase.COMPLETED
                        return

                    # New job registration
                    new_walltime = job.allocation.walltime - (self.time - job.allocation.start_time)
                    assert new_walltime > 0
                    parallel_homogeneous_profile = Profiles.ParallelHomogeneous(
                        cpu=static_job.profile.cpu,
                        com=static_job.profile.com,
                    )
                    static_job.submit_sub_job(static_job.requested_resources, new_walltime,
                                              parallel_homogeneous_profile)
                    self._create_sub_job_objects(static_job)

                    # New job schedule
                    next_job: Job = static_job.sub_jobs.last
                    new_allocation = Allocation(
                        start_time=self.time,
                        walltime=new_walltime,
                        resources=static_job.assigned_compute_resources
                    )
                    next_job.schedule(new_allocation)
                    static_job.phase = JobPhase.RUNNING

                # All stage-out jobs finished
                elif static_job.phase == JobPhase.STAGE_OUT:
                    self._increase_num_completed_jobs()
                    self._free_burst_buffers(static_job)
                    static_job.phase = JobPhase.COMPLETED
                else:
                    assert False

        elif job.profile.type == Profiles.ParallelHomogeneous.type:
            if not job.success:
                self._increase_num_completed_jobs()
                self._free_burst_buffers(static_job)
                static_job.phase = JobPhase.COMPLETED
                return

            # Register stage-out jobs
            new_walltime = job.allocation.walltime - (self.time - job.allocation.start_time)
            assert new_walltime > 0
            stage_out_profile = Profiles.DataStaging(size=job.profile.bb)
            for _ in range(static_job.requested_resources):
                static_job.submit_sub_job(2, new_walltime, stage_out_profile)
            self._create_sub_job_objects(static_job)

            # Schedule stage-out jobs
            for stage_out_job, storage_resource in zip(static_job.sub_jobs.runnable,
                                                       static_job.assigned_burst_buffers.values()):
                self._schedule_data_staging(
                    job=stage_out_job,
                    source=storage_resource,
                    destination=self._pfs,
                    walltime=new_walltime
                )

            static_job.phase = JobPhase.STAGE_OUT

        elif job.profile.type == Profiles.ParallelPFS.type:
            pass

        else:
            assert False

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
        self._allocate_burst_buffers(self.time, self.time + static_job.requested_time,
                                     assigned_burst_buffers, static_job)

        # Schedule all stage-in jobs
        assert len(static_job.sub_jobs) == len(assigned_burst_buffers.values())
        for stage_in_job, storage_resource in zip(static_job.sub_jobs,
                                                  assigned_burst_buffers.values()):
            self._schedule_data_staging(
                job=stage_in_job,
                source=self._pfs,
                destination=storage_resource,
                walltime=static_job.requested_time
            )

        static_job.reject('Static job scheduled')
        static_job.phase = JobPhase.STAGE_IN

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

    # TODO: could return Jobs object
    def _create_sub_job_objects(self, job: Job):
        """
        Creates high-level Job objects for submitted JobDescription of sub-jobs of the given job.
        Must be called after a sequence of job.submit_sub_job() calls if --acknowledge-dynamic-jobs
        flag is not specified for Batsim simulator.
        """
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

    def _increase_num_completed_jobs(self):
        self._num_completed_jobs += 1
        self._progress_bar.update()
        # Only static jobs count
        if self._num_completed_jobs >= self._num_all_jobs:
            assert self._batsim.no_more_static_jobs
            self.notify_registration_finished()
