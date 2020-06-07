from collections import Counter
from typing import Optional, List, Dict, Callable
from tqdm import tqdm

from batsim.sched.resource import Resources, Resource
from batsim.sched.alloc import Allocation
from batsim.sched.job import Job
from batsim.sched.scheduler import Scheduler
from batsim.sched.algorithms.utils import consecutive_resources_filter, generate_resources_filter
from procset import ProcSet

from burstbuffer.storage_resource import StorageResource
from burstbuffer.model import read_config, Platform


# Convention
# node_id is an id of the node from the platform file. It is extracted from the name.
# id is an integer assigned by Batsim to a node.
# There exists a mapping between ids and node_ids.
# node_ids are sorted by Batsim lexicographically.
class AllocOnlyScheduler(Scheduler):
    """Only allocates burst buffers without executing any data transfers to burst buffers."""

    def __init__(self, options):
        super().__init__(options=options)
        if options['progress_bar']:
            # To Turn off Batsim object logging a flag -v 'warn' needs to be passed to the launcher.
            # Turns off Scheduler object logging to display a progress bar.
            self._logger._logger.setLevel('WARNING')
            self.disable_progress_bar = False
        else:
            self.disable_progress_bar = True
        self._event_logger._logger.setLevel('WARNING')

        platform_config = read_config(options['platform'])
        self.platform = Platform(platform_config)
        self._allow_schedule_without_burst_buffer = \
            bool(options['allow_schedule_without_burst_buffer'])

        self._pfs_id: int
        self._burst_buffers = Resources()
        self._burst_buffer_allocations: Dict[int, List[int]] = {}  # job.id -> [burst_buffer_ids]
        # compute_node_id -> [chassis_bb_id, group_bb_id, all_bb_id]
        self._burst_buffer_proximity: Dict[int, List[List[int]]]
        self._ordered_compute_resource_ids: List[int]

        self.filler_not_enough_compute_resource_count = 0
        self.filler_not_enough_burst_buffer_count = 0
        self.backfill_not_enough_burst_buffer_count = 0

    def on_init(self):
        self._print_node_mapping()
        # Storage machines are all burst buffers hosts plus pfs host.
        assert self.platform.num_burst_buffers == len(self.machines['storage']) - 1
        assert self.platform.num_nodes == \
            len(self.machines['storage']) - 1 + len(self.machines['compute'])

        for storage_resource in self.machines['storage']:
            if storage_resource['name'] == 'pfs':
                self._pfs_id = storage_resource['id']
            else:
                self._burst_buffers.add(StorageResource(
                    self,
                    id=storage_resource['id'],
                    name=storage_resource['name'],
                    resources_list=self._burst_buffers,
                    capacity_bytes=self.platform.burst_buffer_capacity
                ))

        self._create_ordered_compute_resource_ids()
        self._create_burst_buffer_proximity()

        # self._resource_filter = consecutive_resources_filter
        self._resource_filter = self._create_resource_filter()
        # self._resource_filter = None

        # Assume also that the number of job profiles equal to the number of static jobs.
        num_all_jobs = sum(len(workload_profiles) for workload_profiles
                           in self._batsim.profiles.values())
        self.progress_bar = tqdm(total=num_all_jobs, smoothing=0, disable=self.disable_progress_bar)

    def on_job_submission(self, job):
        self._validate_job(job)

    def on_job_completion(self, job):
        self._free_burst_buffers(job)
        self.progress_bar.update()

    def on_end(self):
        self.progress_bar.close()
        print('# filler job schedulings with insufficient compute resources: {}'.format(
            self.filler_not_enough_compute_resource_count))
        print('# filler job schedulings with insufficient burst buffers: {}'.format(
            self.filler_not_enough_burst_buffer_count))
        print('# backfill job schedulings with insufficient burst buffers: {}'.format(
            self.backfill_not_enough_burst_buffer_count))

    def schedule(self):
        raise NotImplementedError

    def _filler_schedule(self, jobs=None, abort_on_first_nonfitting=True):
        if jobs is None:
            jobs = self.jobs.runnable

        for job in jobs:
            if not job.runnable:
                self._logger.info('Job {} is not runnable', job.id)
                continue

            was_job_scheduled = False
            assigned_resources = self._find_all_resources(job)
            if assigned_resources:
                assigned_compute_resources, assigned_burst_buffers = assigned_resources
                if assigned_burst_buffers:
                    self._allocate_burst_buffers(self.time,
                                                 self.time + job.requested_time,
                                                 assigned_burst_buffers,
                                                 job)
                    job.schedule(assigned_compute_resources)
                    was_job_scheduled = True
                elif self._allow_schedule_without_burst_buffer:
                    job.schedule(assigned_compute_resources)
                    was_job_scheduled = True

            if not was_job_scheduled and abort_on_first_nonfitting:
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
            # Current time at the beginning.
            # TODO: add epsilon to end times of burst buffer allocations. Intervals in burst
            #  buffer allocation tree are open from the right side. For compute resources they
            #  might be closed.
            allocation_end_times = [self.time] + self._get_burst_buffer_allocation_end_times()

            for time_point in allocation_end_times:
                # Find earliest compute resources for a given starting point in time.
                start_time, assigned_compute_resources = \
                    self.resources.compute.find_with_earliest_start_time(
                        job,
                        allow_future_allocations=True,
                        filter=self._resource_filter,
                        time=time_point
                    )
                assert assigned_compute_resources, 'Not found enough compute resources.'
                end_time = start_time + job.requested_time

                # Check if for a given time interval there are sufficient burst buffer resources.
                assigned_burst_buffers = self._find_sufficient_burst_buffers(
                    assigned_compute_resources,
                    start_time,
                    end_time,
                    job.profile.bb)

                if assigned_burst_buffers:
                    # What is the meaning of the flag self._allocated (active) of Allocation object?
                    # compute_allocation.allocate_all(self)
                    self._allocate_burst_buffers(start_time, end_time, assigned_burst_buffers, job)
                    compute_allocation = Allocation(start_time,
                                                    resources=assigned_compute_resources,
                                                    job=job)
                    temporary_allocations.append(compute_allocation)
                    break
                elif self._allow_schedule_without_burst_buffer:
                    self.backfill_not_enough_burst_buffer_count += 1
                    compute_allocation = Allocation(start_time,
                                                    resources=assigned_compute_resources,
                                                    job=job)
                    temporary_allocations.append(compute_allocation)
                    break

            # After initial filtering of jobs on submission it should be always possible to find
            # enough burst buffers at some point in time.
            assert assigned_burst_buffers, 'Not found enough burst buffer resources.'

        # Allocation for reserved jobs was successful.
        assert len(temporary_allocations) == len(reserved_jobs)
        self._filler_schedule(jobs=remaining_jobs, abort_on_first_nonfitting=False)

        for compute_allocation in temporary_allocations:
            job = compute_allocation.job
            self._free_burst_buffers(job)
            compute_allocation.remove_all_resources()
            # Necessary when allocate_all() was called.
            # compute_allocation.free()

    def _get_burst_buffer_allocation_end_times(self):
        """
        Helper function for backfilling.
        Returns a sorted list over end times of all allocations of all burst buffers.
        """
        alloc_end_times = set()
        for storage_resource in self._burst_buffers:
            alloc_end_times |= storage_resource.get_allocation_end_times()
        return sorted(alloc_end_times)

    def _find_all_resources(self, job: Job):
        """Returns (assigned_compute_resources, assigned_storage_resources) or None."""
        assigned_compute_resources = self.resources.compute.find_sufficient_resources_for_job(
            job, filter=self._resource_filter)
        if assigned_compute_resources:
            assigned_burst_buffers = self._find_sufficient_burst_buffers(
                assigned_compute_resources,
                start_time=self.time,
                end_time=self.time+job.requested_time,
                requested_space=job.profile.bb)
            if not assigned_burst_buffers:
                self.filler_not_enough_burst_buffer_count += 1
            # assigned_burst_buffers may be None here, which means that no sufficient burst buffer
            # was assigned.
            return assigned_compute_resources, assigned_burst_buffers
        else:
            self.filler_not_enough_compute_resource_count += 1
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
        self._burst_buffer_allocations[job.id] = list(burst_buffer_id_counter.keys())

    def _free_burst_buffers(self, job):
        assert job.id in self._burst_buffer_allocations or self._allow_schedule_without_burst_buffer
        if job.id in self._burst_buffer_allocations:
            for burst_buffer_id in self._burst_buffer_allocations[job.id]:
                burst_buffer = self._burst_buffers[burst_buffer_id]
                burst_buffer.free(job)
            del self._burst_buffer_allocations[job.id]

    def _validate_job(self, job: Job) -> bool:
        if job.requested_resources > len(self.resources.compute):
            job.reject("Too few resources available in the system (overall)")
            return False
        # Requested space for a single node must fit within single burst buffer.
        if job.profile.bb > self.platform.burst_buffer_capacity:
            job.reject('Too much requested burst buffer space for a single node.')
            return False
        # Number of how many times job.profile.bb could fit as a whole in total burst buffer
        # space.
        if job.requested_resources > (self.platform.burst_buffer_capacity // job.profile.bb) * \
                len(self._burst_buffers):
            job.reject('Too much total requested burst buffer space.')
            return False
        return True

    def _create_ordered_compute_resource_ids(self):
        """Creates a list of compute resource ids ordered according to Dragonfly topology."""
        self._ordered_compute_resource_ids = []
        num_nodes_in_chassis = self.platform.num_routers * self.platform.num_nodes_per_router
        for node_id in range(self.platform.num_nodes):
            if node_id % num_nodes_in_chassis == 0:
                # This is a storage node
                continue
            for compute_resource in self.resources.compute:
                curr_node_id = self.get_node_id(compute_resource.name)
                if curr_node_id == node_id:
                    self._ordered_compute_resource_ids.append(compute_resource.id)
                    break
        assert len(self._ordered_compute_resource_ids) == \
           self.platform.num_nodes - self.platform.num_burst_buffers

    def _create_burst_buffer_proximity(self):
        """Compute resource id to burst buffer id proximity mapping for the Dragonfly topology."""
        self._burst_buffer_proximity = {compute.id: [[], [], []] for compute in
                                        self.resources.compute}
        # Assume that there is one burst buffer node in every chassis
        num_nodes_in_chassis = self.platform.num_routers * self.platform.num_nodes_per_router
        num_nodes_in_group = num_nodes_in_chassis * self.platform.num_chassis
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

    def _create_resource_filter(self):
        # Based on do_filter function from generate_resources_filter in algorithms/utils.py
        def do_filter(
                resources: List[Resource],
                job: Job,
                current_time: float,
                max_entries: int,
                min_entries: int,
                **kwargs):
            assert len(resources) >= min_entries

            available_resources = {res.id for res in resources}
            indices = [index for index, res_id in enumerate(self._ordered_compute_resource_ids)
                       if res_id in available_resources]
            interval_set = ProcSet(*indices)
            decreasing_intervals = list(reversed(sorted(
                (len(interval), interval) for interval in interval_set.intervals())))

            # Find a single continuous interval fitting all requested resources.
            minimal_fitting_interval = None
            for interval_len, interval in decreasing_intervals:
                if interval_len >= min_entries:
                    minimal_fitting_interval = interval
                else:
                    break

            if minimal_fitting_interval:
                result_set = ProcSet(minimal_fitting_interval)[:min_entries]
                pass
            else:
                # Take largest continuous intervals until sufficient number of resources is found.
                result_set = ProcSet()
                for interval_len, interval in decreasing_intervals:
                    if len(result_set) + interval_len >= min_entries:
                        result_set.insert(*ProcSet(interval)[:min_entries-len(result_set)])
                        break
                    else:
                        result_set.insert(interval)
            assert len(result_set) == min_entries

            # Map back from indices to resources
            filtered_ids = {self._ordered_compute_resource_ids[index] for index in result_set}
            filtered_resources = [res for res in resources if res.id in filtered_ids]
            assert len(filtered_resources) == min_entries
            return filtered_resources

        return do_filter

    def _create_resource_filter_from_generator(self):
        # Doesn't work due to a false assumption in generate_resources_filter.
        def bb_filter_func_consecutive_resources(
                current_time,
                job,
                min_entries,
                max_entries,
                current_result,
                current_remaining,
                r):
            if not current_result:
                return True
            last_id = current_result[-1].id
            index = self._ordered_compute_resource_ids.index(last_id)
            n = len(self._ordered_compute_resource_ids)
            prev_id = self._ordered_compute_resource_ids[(index - 1) % n]
            next_id = self._ordered_compute_resource_ids[(index + 1) % n]
            return r.id == prev_id or r.id == next_id

        bb_consecutive_resources_filter = generate_resources_filter(
            [bb_filter_func_consecutive_resources], [])
        return bb_consecutive_resources_filter

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
