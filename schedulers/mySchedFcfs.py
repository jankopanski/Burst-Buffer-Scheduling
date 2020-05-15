from typing import Optional, List, Dict, Set
from collections import Counter
from batsim.sched.resource import Resource, Resources
from batsim.sched.alloc import Allocation
from batsim.sched.job import Job
from batsim.sched.scheduler import Scheduler
from batsim.sched.algorithms.filling import filler_sched
from batsim.sched.algorithms.utils import consecutive_resources_filter
from intervaltree import Interval, IntervalTree


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


# Only allocates burst buffers without executing any data transfers to burst buffers
# class BaseAllocOnlyScheduler(Scheduler):

# Convention
# node_id is an id of the node from the platform file. It is extracted from the name.
# id is an integer assigned by Batsim to a node.
# There exists a mapping between ids and node_ids.
# node_ids are sorted by Batsim lexicographically.
class MySchedFcfs(Scheduler):
    BURST_BUFFER_CAPACITY_GB = 5
    NUM_GROUPS, NUM_CHASSIS, NUM_ROUTERS, NUM_NODES_PER_ROUTER = 3, 2, 3, 2
    BURST_BUFFER_CAPACITY_BYTES = BURST_BUFFER_CAPACITY_GB * 10 ** 9
    NUM_NODES = NUM_GROUPS * NUM_CHASSIS * NUM_ROUTERS * NUM_NODES_PER_ROUTER
    NUM_BURST_BUFFERS = NUM_GROUPS * NUM_CHASSIS

    def __init__(self, options={}):
        super().__init__(options=options)
        self._pfs_id: int
        self._burst_buffers = Resources()
        self._burst_buffer_allocations: Dict[int, List[int]] = {}  # job.id -> burst_buffer_ids
        # compute_node_id -> [chassis_bb_id, group_bb_id, all_bb_id]
        self._burst_buffer_proximity: Dict[int, List[List[int]]]

    def on_init(self):
        self._print_node_mapping()
        # Storage machines are all burst buffers hosts plus pfs host.
        assert len(self.machines['storage']) - 1 == self.NUM_BURST_BUFFERS
        assert len(self.machines['storage']) - 1 + len(self.machines['compute']) == self.NUM_NODES
        for storage_resource in self.machines['storage']:
            if storage_resource['name'] == 'pfs':
                self._pfs_id = storage_resource['id']
            else:
                self._burst_buffers.add(StorageResource(
                    self,
                    id=storage_resource['id'],
                    name=storage_resource['name'],
                    resources_list=self._burst_buffers,
                    capacity_bytes=self.BURST_BUFFER_CAPACITY_BYTES))
        self._create_burst_buffer_proximity()

    def schedule(self):
        # MySchedFcfsFun(self)
        # self._filler_schedule()
        self._backfill_schedule()

    def on_job_submission(self, job):
        self._validate_job(job)

    def on_job_completion(self, job):
        self._free_burst_buffers(job)

    def _filler_schedule(self, jobs=None, abort_on_first_nonfitting=True):
        if jobs is None:
            jobs = self.jobs.runnable

        for job in jobs:
            if not job.runnable:
                self._logger.info('Job {} is not runnable', job.id)
                continue
            assigned_resources = self._find_all_resources(job)
            if assigned_resources:
                assigned_compute_resources, assigned_burst_buffers = assigned_resources
                self._allocate_burst_buffers(self.time,
                                             self.time + job.requested_time,
                                             assigned_burst_buffers,
                                             job)
                job.schedule(assigned_compute_resources)
            elif abort_on_first_nonfitting:
                break

    def _backfill_schedule(self, backfilling_reservation_depth=1):
        self._filler_schedule()

        if not self.jobs.open:
            return
        assert len(self.jobs.open) == len(self.jobs.runnable), 'Jobs do not have any dependencies.'

        reserved_jobs = self.jobs.runnable[:backfilling_reservation_depth]
        remaining_jobs = self.jobs.runnable[backfilling_reservation_depth:]

        # Allocate compute and storage resources for reserved jobs in the future.
        temporary_allocations = []
        for job in reserved_jobs:
            start_time, assigned_compute_resources = self.resources.compute.find_with_earliest_start_time(
                job,
                allow_future_allocations=True,
                filter=consecutive_resources_filter,
                time=self.time
            )
            end_time = start_time + job.requested_time
            assert assigned_compute_resources
            assigned_burst_buffers = self._find_sufficient_burst_buffers(
                assigned_compute_resources,
                start_time,
                end_time,
                job.profile.bb)
            if assigned_burst_buffers is None:
                break
            compute_allocation = Allocation(start_time,
                                            resources=assigned_compute_resources,
                                            job=job)
            # What is the meaning of the flag self._allocated (active) of Allocation object?
            # compute_allocation.allocate_all(self)
            self._allocate_burst_buffers(start_time, end_time, assigned_burst_buffers, job)
            temporary_allocations.append(compute_allocation)

        # Allocation for reserved jobs was successful.
        if len(temporary_allocations) == len(reserved_jobs):
            self._filler_schedule(jobs=remaining_jobs, abort_on_first_nonfitting=False)

        for compute_allocation in temporary_allocations:
            job = compute_allocation.job
            self._free_burst_buffers(job)
            compute_allocation.remove_all_resources()
            # Necessary when allocate_all() was called.
            # compute_allocation.free()

    def _find_all_resources(self, job: Job):
        """Returns (assigned_compute_resources, assigned_storage_resources) or None."""
        assigned_compute_resources = self.resources.compute.find_sufficient_resources_for_job(
            job, filter=consecutive_resources_filter)
        if assigned_compute_resources:
            assigned_burst_buffers = self._find_sufficient_burst_buffers(
                assigned_compute_resources,
                start_time=self.time,
                end_time=self.time+job.requested_time,
                requested_space=job.profile.bb)
            if assigned_burst_buffers:
                return assigned_compute_resources, assigned_burst_buffers
        return None

    def _find_sufficient_burst_buffers(self,
                                       assigned_compute_resources: Resources,
                                       start_time: float,
                                       end_time: float,
                                       requested_space: int) -> Optional[Dict[int, int]]:
        """Returns a mapping compute_resource_id -> burst_buffer_id."""
        assigned_burst_buffers = {}
        available_space = {burst_buffer.id: burst_buffer.available_space(start_time, end_time)
                           for burst_buffer in self._burst_buffers}
        for compute_resource in assigned_compute_resources:
            was_burst_buffer_assigned = False
            for burst_buffer_proximity_layer in self._burst_buffer_proximity[compute_resource.id]:
                if was_burst_buffer_assigned:
                    break
                for burst_buffer_id in burst_buffer_proximity_layer:
                    if available_space[burst_buffer_id] >= requested_space:
                        available_space[burst_buffer_id] -= requested_space
                        assigned_burst_buffers[compute_resource.id] = burst_buffer_id
                        was_burst_buffer_assigned = True
                        break
        if len(assigned_burst_buffers) == len(assigned_compute_resources):
            return assigned_burst_buffers
        return None

    def _allocate_burst_buffers(self,
                                start: float,
                                end: float,
                                assigned_burst_buffers: Dict[int, int],
                                job: Job):
        burst_buffer_id_counter = Counter(assigned_burst_buffers.values())
        for burst_buffer_id, count in burst_buffer_id_counter.items():
            burst_buffer = self._burst_buffers[burst_buffer_id]
            requested_space = count * job.profile.bb
            burst_buffer.allocate(start, end, requested_space, job)
        self._burst_buffer_allocations[job.id] = burst_buffer_id_counter.keys()

    def _free_burst_buffers(self, job):
        for burst_buffer_id in self._burst_buffer_allocations[job.id]:
            burst_buffer = self._burst_buffers[burst_buffer_id]
            burst_buffer.free(job)
        del self._burst_buffer_allocations[job.id]

    def _validate_job(self, job: Job) -> bool:
        if job.requested_resources > len(self.resources.compute):
            job.reject("Too few resources available in the system (overall)")
            return False
        # Requested space for a single node must fit within single burst buffer.
        if job.profile.bb > self.BURST_BUFFER_CAPACITY_BYTES:
            job.reject('Too much requested burst buffer space for a single node.')
            return False
        # Number of how many times job.profile.bb could fit as a whole in total burst buffer
        # space.
        if job.requested_resources > (self.BURST_BUFFER_CAPACITY_BYTES // job.profile.bb) * \
                len(self._burst_buffers):
            job.reject('Too much total requested burst buffer space.')
            return False
        return True

    def _create_burst_buffer_proximity(self):
        """Compute resource id to burst buffer id proximity mapping for the Dragonfly topology."""
        self._burst_buffer_proximity = {compute.id: [[], [], []] for compute in
                                        self.resources.compute}
        # Assume that there is one burst buffer node in every chassis
        num_nodes_in_chassis = self.NUM_ROUTERS * self.NUM_NODES_PER_ROUTER
        num_nodes_in_group = num_nodes_in_chassis * self.NUM_CHASSIS
        burst_buffer_node_id_to_id = {self.get_node_id(bb.name): bb.id for bb in
                                      self._burst_buffers}
        assert all([bb_node_id % num_nodes_in_chassis == 0 for bb_node_id in
                    burst_buffer_node_id_to_id.keys()])

        for compute_resource in self.resources.compute:
            node_id = self.get_node_id(compute_resource.name)
            chassis_bb_node_id = (node_id // num_nodes_in_chassis) * num_nodes_in_chassis
            self._burst_buffer_proximity[compute_resource.id][0] = \
                [burst_buffer_node_id_to_id[chassis_bb_node_id]]

            first_bb_node_id_in_group = (node_id // num_nodes_in_group) * num_nodes_in_group
            for bb_node_id in range(first_bb_node_id_in_group,
                                    first_bb_node_id_in_group + num_nodes_in_group,
                                    num_nodes_in_chassis):
                if bb_node_id != chassis_bb_node_id:
                    self._burst_buffer_proximity[compute_resource.id][1].append(
                        burst_buffer_node_id_to_id[bb_node_id])

            self._burst_buffer_proximity[compute_resource.id][2] = \
                list(set(burst_buffer_node_id_to_id.values()) -
                     set(self._burst_buffer_proximity[compute_resource.id][0]) -
                     set(self._burst_buffer_proximity[compute_resource.id][1]))

    def _print_node_mapping(self):
        for node in self.machines['compute']:
            print('compute node: {} -> {}'.format(node['name'], node['id']))
        for node in self.machines['storage']:
            print('storage node: {} -> {}'.format(node['name'], node['id']))

    @staticmethod
    def get_node_id(node_name):
        """Gets platform node id from the name in the platform file.
        For 'node_42' will return 42.
        """
        return int(node_name.split('_')[-1])


def MySchedFcfsFun(scheduler):
    return filler_sched(
        scheduler,
        resources_filter=consecutive_resources_filter,
        abort_on_first_nonfitting=True)
