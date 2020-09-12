from typing import Dict

from intervaltree import Interval, IntervalTree
from batsim.sched.resource import Resource, Resources
from batsim.sched.job import Job
from batsim.sched.scheduler import Scheduler
from batsim.sched.alloc import Allocation


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
        self._capacity = capacity_bytes
        self._job_allocations: Dict[int, Interval] = {}  # job_id -> [(start, end, num_bytes)]
        self._interval_tree = IntervalTree()

    def available_space(self, start: float, end: float) -> int:
        """Available space in the storage resource in a time range (start, end)."""
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

        assert max_allocated_space <= self._capacity
        return self._capacity - max_allocated_space

    def allocate(self, start: float, end: float, num_bytes: int, job: Job):
        assert self._scheduler.time <= start <= end
        assert 0 < num_bytes <= self.available_space(start, end)
        # There should be only one interval per job.
        assert job.id not in self._job_allocations
        interval = Interval(start, end, num_bytes)
        self._job_allocations[job.id] = interval
        self._interval_tree.add(interval)

    def free(self, job: Job):
        interval = self._job_allocations[job.id]
        self._interval_tree.remove(interval)
        del self._job_allocations[job.id]

    def find_first_time_to_fit_job(self, job, time=None,
                                   future_reservation=False):
        raise NotImplementedError('Later')

    def get_allocation_end_times(self):
        return set(interval.end for interval in self._job_allocations.values())