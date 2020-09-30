from typing import Dict

from intervaltree import Interval, IntervalTree
from batsim.sched import Resource, Resources, Allocation, Job, Scheduler

from .types import JobId


class StorageAllocation(Allocation):
    """This class is introduce only to make DataStaging profile work."""
    def __len__(self):
        return len(self.special_resources)


class StorageResource(Resource):
    def __init__(
            self,
            scheduler: Scheduler,
            name: str,
            id: int,
            resources_list: Resources = None,
            capacity_bytes: int = 0):
        super().__init__(scheduler, name, id, resources_list,
                         resource_sharing=True)
        self.capacity = capacity_bytes
        self._job_allocations: Dict[JobId, Interval] = {}  # job_id -> [(start, end, num_bytes)]
        self._interval_tree = IntervalTree()

    def currently_allocated_space(self) -> int:
        intervals = self._interval_tree[self._scheduler.time]
        allocated_space = sum(interval.data for interval in intervals)
        assert allocated_space <= self.capacity
        return allocated_space

    def available_space(self, start: float, end: float) -> int:
        """
        Available space in the storage resource in a time range (start, end).
        Should be the same as self._interval_tree.envelop(start, end).
        """
        intervals = self._interval_tree[start:end]
        interval_starts = [(interval.begin, interval.data) for interval in intervals]
        interval_ends = [(interval.end, -interval.data) for interval in intervals]
        interval_points = sorted(interval_starts + interval_ends)  # (time, value)

        # Compute max of prefix sum
        max_allocated_space = 0
        curr_allocated_space = 0
        for _, value in interval_points:
            curr_allocated_space += value
            max_allocated_space = max(max_allocated_space, curr_allocated_space)

        assert max_allocated_space <= self.capacity
        return self.capacity - max_allocated_space

    def allocate(self, start: float, end: float, num_bytes: int, job: Job):
        assert self._scheduler.time <= start <= end
        assert 0 < num_bytes <= self.available_space(start, end)
        # There should be only one interval per job.
        assert job.id not in self._job_allocations
        interval = Interval(start, end, num_bytes)
        self._job_allocations[job.id] = interval
        self._interval_tree.add(interval)
        assert bool(not self._job_allocations) == bool(self._interval_tree.is_empty())
        assert len(self._job_allocations) == len(self._interval_tree.all_intervals)
        if __debug__:
            self._interval_tree.verify()

    def free(self, job: Job):
        interval = self._job_allocations[job.id]
        self._interval_tree.remove(interval)
        del self._job_allocations[job.id]
        assert bool(not self._job_allocations) == bool(self._interval_tree.is_empty())
        assert len(self._job_allocations) == len(self._interval_tree.all_intervals)
        if __debug__:
            self._interval_tree.verify()

    def find_first_time_to_fit_job(self, job, time=None, future_reservation=False):
        raise NotImplementedError

    def get_allocation_end_times(self):
        return set(interval.end for interval in self._job_allocations.values())
