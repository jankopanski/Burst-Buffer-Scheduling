from collections import Counter
from functools import partial
from itertools import permutations
from math import factorial, floor, ceil, inf, exp
from operator import itemgetter, attrgetter
from random import seed, randint, random, shuffle
from typing import Optional, List, Dict, Callable, Tuple, Iterable, Iterator
from tqdm import tqdm
from sortedcontainers import SortedSet
from simanneal import Annealer
import z3

from batsim.batsim import Batsim
from batsim.sched.resource import Resources, Resource, ComputeResource
from batsim.sched.alloc import Allocation
from batsim.sched.job import Job, Jobs
from batsim.sched.scheduler import Scheduler
from batsim.sched.algorithms.utils import generate_resources_filter
from procset import ProcSet

from .types import *
from .storage import StorageResource
from .platform import read_config, Platform


# Convention
# node_id is an id of the node from the platform file. It is extracted from the name.
# id is an integer assigned by Batsim to a node.
# There exists a mapping between ids and node_ids.
# node_ids are sorted by Batsim lexicographically.
class AllocOnlyScheduler(Scheduler):
    """
    Only allocates burst buffers without executing any data transfers to burst buffers.
    """

    _batsim: Batsim
    # compute_node_id -> [chassis_bb_id, group_bb_id, all_bb_id]
    _burst_buffers: Resources
    _burst_buffer_allocations: Dict[JobId, List[StorageResourceId]]
    _burst_buffer_proximity: Dict[ComputeResourceId, List[List[StorageResourceId]]]
    _num_all_jobs: int
    _ordered_compute_resource_ids: List[ComputeResourceId]
    _progress_bar: tqdm
    _pfs: StorageResource

    def __init__(self, options):
        super().__init__(options=options)
        if options['progress_bar']:
            # To Turn off Batsim object logging a flag -v 'warn' needs to be passed to the launcher.
            # Turns off Scheduler object logging to display a progress bar.
            self._logger._logger.setLevel('WARNING')
            self._disable_progress_bar = False
        else:
            self._disable_progress_bar = True
        self._event_logger._logger.setLevel('WARNING')

        seed(42)
        self.allow_schedule = True
        self.last_job_ids = []

        # Platform configuration and other options from scheduler_options.json
        platform_config = read_config(options['platform'])
        self.platform = Platform(platform_config)
        self.algorithm = options['algorithm']
        assert self.algorithm in ['fcfs', 'filler', 'backfill', 'moo', 'maxutil', 'plan']
        self.allow_schedule_without_burst_buffer = bool(
            options['allow_schedule_without_burst_buffer'])
        self.future_burst_buffer_reservation = bool(options['future_burst_buffer_reservation'])
        self.backfilling_reservation_depth = int(options['backfilling_reservation_depth'])
        assert self.backfilling_reservation_depth >= 1
        self.balance_factor = float(options['balance_factor'])
        assert self.balance_factor >= 0
        self.compute_threshold = float(options['compute_threshold'])
        self.storage_threshold = float(options['storage_threshold'])
        self.priority_policy = options['priority_policy']
        assert self.priority_policy in [
            None, 'sjf',
            'largest', 'smallest', 'ratio',
            'maxsort', 'maxperm',
            'sum', 'square', 'start', 'makespan']
        self.optimisation = bool(options['optimisation'])

        # Resource initialisation
        self._burst_buffers = Resources()
        # job.id -> [burst_buffer_ids]
        self._burst_buffer_allocations = {}

        self.reject_compute_resources = 0
        self.reject_burst_buffer_capacity = 0
        self.reject_total_burst_buffer = 0
        self.filler_not_enough_compute_resource_count = 0
        self.filler_not_enough_burst_buffer_count = 0
        self.backfill_not_enough_burst_buffer_count = 0

    def on_init(self):
        # TODO: add a switch option
        # self._print_node_mapping()

        # Storage machines are all burst buffers hosts plus pfs host.
        assert self.platform.num_burst_buffers == len(self.machines['storage']) - 1
        assert self.platform.num_all_nodes == \
               len(self.machines['storage']) - 1 + len(self.machines['compute'])

        for storage_resource in self.machines['storage']:
            if storage_resource['name'] == 'pfs':
                self._pfs = StorageResource(
                    scheduler=self,
                    id=storage_resource["id"],
                    name=storage_resource["name"],
                    resources_list=self.resources
                )
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

        # self._resource_filter = None
        # self._resource_filter = consecutive_resources_filter
        self._resource_filter = self._create_resource_filter()

        # Assume also that the number of job profiles equal to the number of static jobs.
        self._num_all_jobs = sum(len(workload_profiles) for workload_profiles
                                 in self._batsim.profiles.values())
        self._progress_bar = tqdm(total=self._num_all_jobs, smoothing=0.1,
                                  disable=self._disable_progress_bar)

    def on_job_submission(self, job):
        job.comment = job.profile.bb
        self._validate_job(job)

    def on_job_completion(self, job):
        self.allow_schedule = True
        self._free_burst_buffers(job)
        self._progress_bar.update()

    def on_end(self):
        self._progress_bar.close()
        print('# Rejected jobs: Too few resources available in the system (overall): ',
              self.reject_compute_resources)
        print('# Rejected jobs: Too much requested burst buffer space for a single node: ',
              self.reject_burst_buffer_capacity)
        print('# Rejected jobs: Too much total requested burst buffer space: ',
              self.reject_total_burst_buffer)
        print('# filler job schedulings with insufficient compute resources: {}'.format(
            self.filler_not_enough_compute_resource_count))
        print('# filler job schedulings with insufficient burst buffers: {}'.format(
            self.filler_not_enough_burst_buffer_count))
        print('# backfill job schedulings with insufficient burst buffers: {}'.format(
            self.backfill_not_enough_burst_buffer_count))

    def schedule(self):
        raise NotImplementedError

    def schedule_job(
            self,
            job: Job,
            assigned_compute_resources: List[ComputeResource],
            assigned_burst_buffers: Dict[ComputeResource, StorageResource]
    ):
        assert assigned_compute_resources
        if assigned_burst_buffers:
            self._allocate_burst_buffers(
                start=self.time,
                end=self.time + job.requested_time,
                assigned_burst_buffers=assigned_burst_buffers,
                job=job
            )
        job.schedule(assigned_compute_resources)

    def filler_schedule(self, jobs=None, abort_on_first_nonfitting=True) -> int:
        """Returns the number of scheduled jobs."""
        if jobs is None:
            jobs = self.jobs.runnable

        num_scheduled = 0
        for job in jobs:
            assert job.runnable

            assigned_compute_resources, assigned_burst_buffers = self._find_all_resources(job)
            if assigned_compute_resources and \
                    (assigned_burst_buffers or self.allow_schedule_without_burst_buffer):
                self.schedule_job(job, assigned_compute_resources, assigned_burst_buffers)
                num_scheduled += 1
            elif abort_on_first_nonfitting:
                break
        return num_scheduled

    def backfill_schedule(
            self,
            jobs=None,
            reservation_depth=1,
            future_burst_buffer_reservation=True,
            priority_policy=None,
            balance_factor=None
    ):
        if jobs is None:
            jobs = self.jobs.runnable
        self.filler_schedule(jobs)

        jobs = jobs.runnable
        if not jobs.open:
            return
        reserved_jobs = jobs[:reservation_depth]
        remaining_jobs = jobs[reservation_depth:]

        temporary_allocations = []
        # Allocate compute and storage resources for reserved jobs in the future.
        if future_burst_buffer_reservation:
            for job in reserved_jobs:
                # Current time at the beginning.
                # TODO: add epsilon to end times of burst buffer allocations. Intervals in burst
                #  buffer allocation tree are open from the right side. For compute resources they
                #  might be closed.
                allocation_end_times = [self.time] + self._get_burst_buffer_allocation_end_times()

                assigned_burst_buffers = None
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

                    # Check if for a given time interval there are sufficient burst buffer
                    # resources.
                    assigned_burst_buffers = self._find_sufficient_burst_buffers(
                        assigned_compute_resources, start_time, end_time, job.profile.bb)

                    if assigned_burst_buffers:
                        # What is the meaning of the flag self._allocated (active) of an Allocation
                        # object?
                        # compute_allocation.allocate_all(self)
                        self._allocate_burst_buffers(start_time, end_time,
                                                     assigned_burst_buffers, job)
                        temporary_allocations.append(Allocation(
                            start_time=start_time,
                            walltime=job.requested_time,
                            resources=assigned_compute_resources,
                            job=job
                        ))
                        break
                    elif self.allow_schedule_without_burst_buffer:
                        self.backfill_not_enough_burst_buffer_count += 1
                        temporary_allocations.append(Allocation(
                            start_time=start_time,
                            walltime=job.requested_time,
                            resources=assigned_compute_resources,
                            job=job
                        ))
                        break
                # After initial filtering of jobs on submission it should be always possible to find
                # enough burst buffers at some point in time.
                assert assigned_burst_buffers or self.allow_schedule_without_burst_buffer, \
                    'Not found enough burst buffer resources.'

        else:
            # Backfilling without future storage reservations
            for job in reserved_jobs:
                start_time, assigned_compute_resources = \
                    self.resources.compute.find_with_earliest_start_time(
                        job,
                        allow_future_allocations=True,
                        filter=self._resource_filter,
                        time=self.time
                    )
                assert assigned_compute_resources, 'Not found enough compute resources.'
                temporary_allocations.append(Allocation(
                    start_time=start_time,
                    walltime=job.requested_time,
                    resources=assigned_compute_resources,
                    job=job
                ))

        # Allocation for reserved jobs was successful.
        assert len(temporary_allocations) == len(reserved_jobs)
        if priority_policy is None:
            self.filler_schedule(remaining_jobs, abort_on_first_nonfitting=False)
        elif priority_policy == 'sjf':
            self.filler_schedule(remaining_jobs.sorted(attrgetter('requested_time')),
                                 abort_on_first_nonfitting=False)
        elif priority_policy == 'maxsort':
            self._maxutil_backfill(AllocOnlyScheduler._sort_iterator(remaining_jobs))
        elif priority_policy == 'maxperm':
            self._maxutil_backfill(AllocOnlyScheduler._permutation_iterator(remaining_jobs))
        elif priority_policy:
            self._balance_backfill(
                jobs=remaining_jobs,
                priority_policy=priority_policy,
                balance_factor=balance_factor
            )
        else:
            assert False

        for compute_allocation in temporary_allocations:
            job = compute_allocation.job
            if future_burst_buffer_reservation:
                self._free_burst_buffers(job)
            compute_allocation.remove_all_resources()
            # Necessary when allocate_all() was called.
            # compute_allocation.free()

    def _balance_backfill(self, jobs: Jobs, priority_policy='ratio', balance_factor=1):
        assert not self.allow_schedule_without_burst_buffer
        assert priority_policy in ['largest', 'smallest', 'ratio']

        while True:
            scheduled = False
            compute_util = self._compute_utilisation()
            storage_util = self._storage_utilisation()
            jobs = jobs.runnable
            sorted_jobs = None
            if compute_util > balance_factor * storage_util:
                if priority_policy == 'largest':
                    # Sort descending by storage
                    sorted_jobs = sorted(((job.profile.bb, job) for job in jobs),
                                         reverse=True, key=itemgetter(0))
                elif priority_policy == 'smallest':
                    # Sort ascending by compute
                    sorted_jobs = sorted(((job.requested_resources, job) for job in jobs),
                                         reverse=False, key=itemgetter(0))
                elif priority_policy == 'ratio':
                    # Sort descending by storage/compute ratio
                    sorted_jobs = sorted(
                        ((job.profile.bb / job.requested_resources, job) for job in jobs),
                        reverse=True, key=itemgetter(0))
            else:
                if priority_policy == 'largest':
                    # Sort descending by compute
                    sorted_jobs = sorted(((job.requested_resources, job) for job in jobs),
                                         reverse=True, key=itemgetter(0))
                elif priority_policy == 'smallest':
                    # Sort ascending by storage
                    sorted_jobs = sorted(((job.profile.bb, job) for job in jobs),
                                         reverse=False, key=itemgetter(0))
                elif priority_policy == 'ratio':
                    # Sort ascending by storage/compute ratio
                    sorted_jobs = sorted(
                        ((job.profile.bb / job.requested_resources, job) for job in jobs),
                        reverse=False, key=itemgetter(0))

            assert sorted_jobs is not None
            for job in (job for _, job in sorted_jobs):
                assigned_compute_resources, assigned_burst_buffers = self._find_all_resources(job)
                if assigned_compute_resources and assigned_burst_buffers:
                    self.schedule_job(job, assigned_compute_resources, assigned_burst_buffers)
                    scheduled = True
                    break

            if not scheduled:
                break

    def _compute_utilisation(self) -> float:
        assert len(self.resources.compute) == self.platform.nb_res
        util = len(self.resources.compute.allocated) / self.platform.nb_res
        assert 0 <= util <= 1
        return util

    def _storage_utilisation(self) -> float:
        assert len(self._burst_buffers) == self.platform.num_burst_buffers
        allocated_space = sum(burst_buffer.currently_allocated_space()
                              for burst_buffer in self._burst_buffers)
        total_capacity = sum(burst_buffer.capacity for burst_buffer in self._burst_buffers)
        assert total_capacity == \
               self.platform.num_burst_buffers * self.platform.burst_buffer_capacity
        util = allocated_space / total_capacity
        assert 0 <= util <= 1
        return util

    def _maxutil_backfill(self, job_permutations: Iterable[Jobs]):
        assert not self.allow_schedule_without_burst_buffer
        unused_compute = self.platform.nb_res - len(self.resources.compute.allocated)
        allocated_space = sum(burst_buffer.currently_allocated_space()
                              for burst_buffer in self._burst_buffers)
        total_capacity = sum(burst_buffer.capacity for burst_buffer in self._burst_buffers)
        unused_storage = total_capacity - allocated_space
        if not unused_compute or not unused_storage:
            return

        best_score = 0
        best_perm_entries = []  # (job, compute, burst_buffer)
        for jobs_perm in job_permutations:
            temporary_allocations = []
            current_perm_entries = []
            compute_time = 0
            storage_time = 0
            for job in jobs_perm:
                assigned_compute_resources, assigned_burst_buffers = self._find_all_resources(job)
                if assigned_compute_resources and assigned_burst_buffers:
                    self._allocate_burst_buffers(
                        start=self.time,
                        end=self.time + job.requested_time,
                        assigned_burst_buffers=assigned_burst_buffers,
                        job=job
                    )
                    temporary_allocations.append(Allocation(
                        start_time=self.time,
                        walltime=job.requested_time,
                        resources=assigned_compute_resources,
                        job=job
                    ))
                    current_perm_entries.append(
                        (job, assigned_compute_resources, assigned_burst_buffers))
                    compute_time += len(assigned_compute_resources) * job.requested_time
                    storage_time += \
                        len(assigned_burst_buffers) * job.profile.bb * job.requested_time

            curr_score = min(compute_time / unused_compute, storage_time / unused_storage)
            if curr_score > best_score:
                best_score = curr_score
                best_perm_entries = current_perm_entries

            for compute_allocation in temporary_allocations:
                job = compute_allocation.job
                self._free_burst_buffers(job)
                compute_allocation.remove_all_resources()

        for job, assigned_compute_resources, assigned_burst_buffers in best_perm_entries:
            self.schedule_job(job, assigned_compute_resources, assigned_burst_buffers)

    def maxutil_schedule(
            self,
            jobs: Jobs = None,
            reservation_depth=1,
            balance_factor=1,
            optimisation=False
    ):
        if jobs is None:
            jobs = self.jobs.runnable

        def mean_waiting_time(plan: ExecutionPlan):
            if not plan:
                return 0
            return sum(start_time - job.submit_time for job, start_time, _, _ in plan) / len(plan)

        def system_utilisation(optimise_compute, plan: ExecutionPlan):
            compute = sum(len(compute_resources) for _, _, compute_resources, _ in plan)
            storage = sum(len(storage_resources) * job.profile.bb
                          for job, _, _, storage_resources in plan)
            wait_time = mean_waiting_time(plan)
            return (compute, storage, wait_time) if optimise_compute else (storage, compute, wait_time)

        compute_queue_util = sum(job.requested_resources for job in jobs) / self.platform.nb_res
        storage_queue_util = sum(
            job.profile.bb * job.requested_resources for job in jobs) / \
                             (self.platform.burst_buffer_capacity * self.platform.num_burst_buffers)

        # If storage utilisation in the queue is small than optimise compute.
        if storage_queue_util <= balance_factor * compute_queue_util:
            score_function = partial(system_utilisation, True)
        else:
            score_function = partial(system_utilisation, False)

        # if compute_queue_util < self.compute_threshold \
        #         and storage_queue_util < self.storage_threshold:
        #     self.backfill_schedule(jobs, reservation_depth, priority_policy='sjf')
        #     return

        num_scheduled = self.filler_schedule(jobs[:reservation_depth])
        priority_jobs = jobs[num_scheduled:reservation_depth]
        remaining_jobs = jobs[reservation_depth:]
        if not remaining_jobs:
            return

        _, priority_allocations = self.create_execution_plan(priority_jobs)

        if len(remaining_jobs) == 1:
            self.filler_schedule(remaining_jobs)
            self.free_allocations(priority_allocations)
            return
        else:
            # Check if any jobs could be started
            plan, _ = self.find_jobs_to_execute(remaining_jobs)
            if not plan:
                self.free_allocations(priority_allocations)
                return
            if len(remaining_jobs) <= 6:
                job_permutations = permutations(remaining_jobs)
                optimisation = False
            else:
                job_permutations = self._sort_iterator(remaining_jobs)

        best_score = (-1, -1, -1)
        best_plan = []
        best_permutation = None
        best_last_index = None
        for job_permutation in job_permutations:
            plan, last_index = self.find_jobs_to_execute(job_permutation)
            score = score_function(plan)
            if score > best_score:
                best_score = score
                best_plan = plan
                best_permutation = job_permutation
                best_last_index = last_index

        assert best_score > (0, 0, 0)
        if optimisation:
            # old_best = best_score
            max_steps = 5000
            steps = 0
            perm = list(best_permutation)
            # from time import time
            # start = time()
            while steps < max_steps:
                new_best = False
                for distance in range(1, len(remaining_jobs)):
                    for index in range(min(best_last_index + 1, len(remaining_jobs) - distance)):
                        steps += 1
                        if steps >= max_steps:
                            break
                        perm[index], perm[index + distance] = perm[index + distance], perm[index]
                        plan, last_index = self.find_jobs_to_execute(perm)
                        score = score_function(plan)
                        if score > best_score:
                            # Accept new permutation
                            best_score = score
                            best_plan = plan
                            best_last_index = last_index
                            new_best = True
                            break
                        # Reject new permutation
                        perm[index], perm[index + distance] = perm[index + distance], perm[index]
                    if new_best or steps >= max_steps:
                        break
                if not new_best:
                    break
            # end = time()
            # if best_score > old_best:
            #     print('IMPROVE!!!', old_best, best_score, end-start)

        for job, _, assigned_compute_resources, assigned_burst_buffers in best_plan:
            self.schedule_job(job, assigned_compute_resources, assigned_burst_buffers)

        self.free_allocations(priority_allocations)

    def find_jobs_to_execute(self, jobs) -> Tuple[ExecutionPlan, int]:
        plan = []
        allocations = []
        last_selected_index = -1
        for i, job in enumerate(jobs):
            assigned_compute_resources, assigned_burst_buffers = self._find_all_resources(job)
            if assigned_compute_resources and assigned_burst_buffers:
                self._allocate_burst_buffers(
                    start=self.time,
                    end=self.time + job.requested_time,
                    assigned_burst_buffers=assigned_burst_buffers,
                    job=job
                )
                allocations.append(Allocation(
                    start_time=self.time,
                    walltime=job.requested_time,
                    resources=assigned_compute_resources,
                    job=job
                ))
                plan.append((job, self.time, assigned_compute_resources, assigned_burst_buffers))
                last_selected_index = i
        self.free_allocations(allocations)
        return plan, last_selected_index

    def plan_schedule(
            self,
            jobs: Jobs = None,
            reservation_depth=1,
            priority_policy='sum',
            optimisation=False
    ):
        if jobs is None:
            jobs = self.jobs.runnable

        def sum_waiting_time(plan: ExecutionPlan):
            return sum(start_time - job.submit_time for job, start_time, _, _ in plan)

        def sum_square_waiting_time(plan: ExecutionPlan):
            return sum((start_time - job.submit_time) ** 2 for job, start_time, _, _ in plan)

        def sum_start_time(plan: ExecutionPlan):
            return sum(start_time - self.time for _, start_time, _, _ in plan)

        def expected_queue_makespan(plan: ExecutionPlan):
            return max(start_time + job.requested_time - self.time for job, start_time, _, _ in plan)

        if priority_policy == 'sum':
            score_function = sum_waiting_time
        elif priority_policy == 'square':
            score_function = sum_square_waiting_time
        elif priority_policy == 'start':
            score_function = sum_start_time
        elif priority_policy == 'makespan':
            score_function = expected_queue_makespan
        else:
            assert False

        num_scheduled = self.filler_schedule(jobs[:reservation_depth])
        priority_jobs = jobs[num_scheduled:reservation_depth]
        remaining_jobs = jobs[reservation_depth:]
        if not remaining_jobs:
            return

        _, priority_allocations = self.create_execution_plan(priority_jobs)

        if len(remaining_jobs) == 1:
            self.filler_schedule(remaining_jobs)
            self.free_allocations(priority_allocations)
            return
        else:
            # Check if any jobs could be started
            plan, _ = self.find_jobs_to_execute(remaining_jobs)
            if not plan:
                self.free_allocations(priority_allocations)
                return
            if len(remaining_jobs) <= 5:
                job_permutations = permutations(remaining_jobs)
                optimisation = False
            else:
                job_permutations = self._sort_iterator(remaining_jobs)

        best_score = inf
        worst_score = -inf
        best_plan = []
        for job_permutation in job_permutations:
            plan, allocations = self.create_execution_plan(job_permutation)
            self.free_allocations(allocations)
            score = round(score_function(plan))
            if score < best_score:
                best_score = score
                best_plan = plan
            worst_score = max(worst_score, score)
        # end = time()
        # print(len(remaining_jobs), end - start)

        if optimisation:
            temperature = worst_score - best_score
            if temperature == 0:
                temperature = 0.1 * best_score
            decay = 0.9
            decay_steps = 40
            const_temp_steps = 6
            # decay = (threshold_temperature / temperature) ** (1. / decay_steps)
            perm = [job for job, _, _, _ in best_plan]
            previous_score = best_score

            # print('best_score: {}, init_temp: {}'.format(best_score, temperature))
            # from time import time
            # start = time()
            for _ in range(decay_steps):
                for _ in range(const_temp_steps):
                    # Transition: select random index and swap neighbour jobs
                    index1 = randint(0, len(perm) - 1)
                    index2 = randint(0, len(perm) - 1)
                    perm[index1], perm[index2] = perm[index2], perm[index1]
                    plan, allocations = self.create_execution_plan(perm)
                    self.free_allocations(allocations)
                    score = round(score_function(plan))
                    # if score > previous_score:
                    #     print(
                    #         'outer: {}, inner: {}, score: {}, prev: {}, temp: {}, prob: {}'.format(
                    #             i, j, score, previous_score, temperature,
                    #             exp((previous_score - score) / temperature)))
                    if score < best_score:
                        previous_score = score
                        best_score = score
                        best_plan = plan
                    elif score < previous_score or \
                            random() < exp((previous_score - score) / temperature):
                        # Accept new state
                        previous_score = score
                    else:
                        # Return to previous state
                        perm[index1], perm[index2] = perm[index2], perm[index1]
                temperature *= decay
            # end = time()
            # print('best_score: {}, previous_score: {}, temp: {}, time: {}'.format(best_score, previous_score, temperature, end - start))

            # annealer = PlanBasedAnnealer(
            #     state=([job for job, _, _, _ in best_plan], best_plan),
            #     scheduler=self,
            #     score_function=score_function
            # )
            # auto_params = annealer.auto(minutes=0.2, steps=10)
            # annealer.set_schedule(auto_params)
            # (_, best_plan), best_score = annealer.anneal()

        for job, start_time, assigned_compute_resources, assigned_burst_buffers in best_plan:
            if start_time == self.time:
                self.schedule_job(job, assigned_compute_resources, assigned_burst_buffers)

        self.free_allocations(priority_allocations)

    def create_execution_plan(self, jobs) -> Tuple[ExecutionPlan, List[Allocation]]:
        plan = []
        allocations = []
        allocation_end_times = SortedSet(self._get_burst_buffer_allocation_end_times())
        allocation_end_times.add(self.time)

        for job in jobs:
            assigned_compute_resources = None
            assigned_burst_buffers = None
            start_time = -inf
            end_time = None

            for time_point in allocation_end_times:
                if time_point < start_time:
                    continue
                # Find earliest compute resources for a given starting point in time.
                start_time, assigned_compute_resources = \
                    self.resources.compute.find_with_earliest_start_time(
                        job,
                        allow_future_allocations=True,
                        filter=self._resource_filter,
                        time=time_point
                    )
                assert start_time != -inf
                assert assigned_compute_resources, 'Not found enough compute resources.'
                end_time = start_time + job.requested_time

                # Check if for a given time interval there are sufficient burst buffer
                # resources.
                assigned_burst_buffers = self._find_sufficient_burst_buffers(
                    assigned_compute_resources, start_time, end_time, job.profile.bb)
                if assigned_burst_buffers:
                    break

            # After initial filtering of jobs on submission it should be always possible to find
            # enough burst buffers at some point in time.
            assert assigned_burst_buffers, 'Not found enough burst buffer resources.'
            self._allocate_burst_buffers(start_time, end_time, assigned_burst_buffers, job)
            allocations.append(Allocation(
                start_time=start_time,
                walltime=job.requested_time,
                resources=assigned_compute_resources,
                job=job
            ))
            allocation_end_times.add(end_time)
            plan.append((job, start_time, assigned_compute_resources, assigned_burst_buffers))

        assert len(allocations) == len(jobs)
        assert len(plan) == len(jobs)
        return plan, allocations

    def free_allocations(self, allocations: List[Allocation]):
        for compute_allocation in allocations:
            job = compute_allocation.job
            self._free_burst_buffers(job)
            compute_allocation.remove_all_resources()

    @staticmethod
    def _permutation_iterator(jobs: Jobs) -> Iterator[Jobs]:
        num_tries = 6
        first_len_limit = 3
        second_len_limit = 5
        n = len(jobs)
        if n <= first_len_limit:
            return permutations(jobs)
        elif n <= second_len_limit:
            fact = factorial(n)
            for perm in permutations(jobs):
                if randint(1, fact) <= num_tries:
                    yield perm
        else:
            job_list = list(jobs)
            for _ in range(num_tries):
                shuffle(job_list)
                yield job_list

    @staticmethod
    def _sort_iterator(jobs: Jobs) -> Iterator[Jobs]:
        jobs_sorts = [
            ('compute-desc', attrgetter('requested_resources'), True),
            ('storage-desc', attrgetter('profile.bb'), True),
            ('ratio-desc', lambda j: j.profile.bb / j.requested_resources, True),
            ('ratio-asc', lambda j: j.profile.bb / j.requested_resources, False),
            ('compute-asc', attrgetter('requested_resources'), False),
            ('storage-asc', attrgetter('profile.bb'), False),
            ('time-asc', attrgetter('requested_time'), False),
            ('time-desc', attrgetter('requested_time'), True),
        ]
        yield jobs
        for sort in jobs_sorts:
            yield jobs.sorted(field_getter=sort[1], reverse=sort[2])

    def moo_schedule(self, jobs: Jobs = None):
        if jobs is None:
            jobs = self.jobs.runnable
        if not jobs:
            return

        max_window = 2
        window_size = min(len(jobs), max_window)

        current_window_job_ids = [job.id for job in jobs[:window_size]]
        if not self.allow_schedule and self.last_job_ids == current_window_job_ids:
            return
        self.last_job_ids = current_window_job_ids
        self.allow_schedule = False

        # Number of requested compute nodes
        N = [job.requested_resources for job in jobs[:window_size]]
        # Size of requested burst buffer per compute node rounded up to kB
        B = [ceil(job.profile.bb / 1000) for job in jobs[:window_size]]

        # i-th job in the window is selected to be scheduled
        a = [z3.Bool('a_{}'.format(i)) for i in range(window_size)]
        # j-th compute node is assigned to i-th job
        c = [[z3.Bool('c_{}_{}'.format(i, j)) for j in range(self.platform.nb_res)]
             for i in range(window_size)]
        # k-th storage node is assigned to j-th compute node
        b = [[z3.Bool('b_{}_{}'.format(j, k)) for k in range(self.platform.num_burst_buffers)]
             for j in range(self.platform.nb_res)]

        z3.set_param('parallel.enable', True)
        o = z3.Optimize()
        o.set(priority='lex')
        o.set('pb.compile_equality', True)

        # First job from the queue must always be selected
        o.add(a[0] == True)
        # Exclude compute nodes that are already in use
        for j, compute_resource in enumerate(self.resources.compute):
            if compute_resource.active:
                for i in range(window_size):
                    o.add(c[i][j] == False)
        # Each application must receive requested number of nodes if selected
        for i in range(window_size):
            proc_count = [(c[i][j], 1) for j in range(self.platform.nb_res)]
            all_proc_not = [z3.Not(c[i][j]) for j in range(self.platform.nb_res)]
            o.add(z3.If(a[i], z3.PbEq(proc_count, N[i]), z3.And(all_proc_not)))
        # Each compute node can be assigned to only one application
        for j in range(self.platform.nb_res):
            # o.add(z3.AtMost(*[c[i][j] for i in range(window_size)], 1))
            o.add(z3.PbLe([(c[i][j], 1) for i in range(window_size)], 1))
        # Each selected compute node is assigned with exactly one storage node
        for j in range(self.platform.nb_res):
            any_proc = [c[i][j] for i in range(window_size)]
            bb_count = [(b[j][k], 1) for k in range(self.platform.num_burst_buffers)]
            all_bb_not = [z3.Not(b[j][k]) for k in range(self.platform.num_burst_buffers)]
            o.add(z3.If(z3.Or(any_proc), z3.PbEq(bb_count, 1), z3.And(all_bb_not)))
        # Limit burst buffer assignments by the available space
        for k, burst_buffer in enumerate(self._burst_buffers):
            storage_sum = [(z3.And(c[i][j], b[j][k]), B[i])
                           for i in range(window_size) for j in range(self.platform.nb_res)]
            # Available burst buffer space rounded down to kB
            BBAvail = floor(
                (burst_buffer.capacity - burst_buffer.currently_allocated_space()) / 1000)
            o.add(z3.PbLe(storage_sum, BBAvail))

        # Maximise compute utilisation
        o.maximize(z3.Sum([z3.If(a[i], N[i], 0) for i in range(window_size)]))
        # Maximise burst buffer utilisation
        o.maximize(z3.Sum([z3.If(a[i], N[i] * B[i], 0) for i in range(window_size)]))

        if o.check() == z3.sat:
            m = o.model()
            for i, job in enumerate(jobs):
                if i >= window_size:
                    break
                if m[a[i]]:
                    assigned_compute_resources = []
                    assigned_burst_buffers = {}
                    for j, compute_resource in enumerate(self.resources.compute):
                        if m[c[i][j]]:
                            assigned_compute_resources.append(compute_resource)
                            for k, burst_buffer in enumerate(self._burst_buffers):
                                if m[b[j][k]]:
                                    assigned_burst_buffers[compute_resource] = burst_buffer
                                    break
                    assert len(assigned_compute_resources) == job.requested_resources
                    assert len(assigned_burst_buffers) == job.requested_resources
                    self.schedule_job(job, assigned_compute_resources, assigned_burst_buffers)
        else:
            print('unsat')

    def _get_burst_buffer_allocation_end_times(self) -> List[float]:
        """
        Helper function for backfilling.
        Returns a sorted list over end times of all allocations of all burst buffers.
        """
        alloc_end_times = set()
        for storage_resource in self._burst_buffers:
            alloc_end_times |= storage_resource.get_allocation_end_times()
        return sorted(alloc_end_times)

    def _find_all_resources(self, job: Job) -> Tuple[
        Optional[List[ComputeResource]], Optional[Dict[ComputeResource, StorageResource]]]:
        """Returns (assigned_compute_resources, assigned_storage_resources)."""
        assigned_compute_resources = self.resources.compute.find_sufficient_resources_for_job(
            job, filter=self._resource_filter)
        if assigned_compute_resources:
            assigned_burst_buffers = self._find_sufficient_burst_buffers(
                assigned_compute_resources,
                start_time=self.time,
                end_time=self.time + job.requested_time,
                requested_space=job.profile.bb)
            if not assigned_burst_buffers:
                self.filler_not_enough_burst_buffer_count += 1
            # assigned_burst_buffers may be None here, which means that no sufficient burst buffer
            # was assigned.
            return assigned_compute_resources, assigned_burst_buffers
        else:
            self.filler_not_enough_compute_resource_count += 1
        return None, None

    def _find_sufficient_burst_buffers(
            self,
            assigned_compute_resources: Resources,
            start_time: float,
            end_time: float,
            requested_space: int
    ) -> Optional[Dict[ComputeResource, StorageResource]]:
        """Returns a mapping compute_resource -> burst_buffer."""
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
                        burst_buffer = self._burst_buffers[burst_buffer_id]
                        assigned_burst_buffers[compute_resource] = burst_buffer
                        was_burst_buffer_assigned = True
                        break
        if len(assigned_burst_buffers) == len(assigned_compute_resources):
            return assigned_burst_buffers
        return None

    def _allocate_burst_buffers(
            self,
            start: float,
            end: float,
            assigned_burst_buffers: Dict[ComputeResource, StorageResource],
            job: Job
    ):
        burst_buffer_id_counter = Counter(burst_buffer.id for burst_buffer
                                          in assigned_burst_buffers.values())
        for burst_buffer_id, count in burst_buffer_id_counter.items():
            burst_buffer = self._burst_buffers[burst_buffer_id]
            requested_space = count * job.profile.bb
            burst_buffer.allocate(start, end, requested_space, job)
        self._burst_buffer_allocations[job.id] = list(burst_buffer_id_counter.keys())

    def _free_burst_buffers(self, job):
        assert job.id in self._burst_buffer_allocations or self.allow_schedule_without_burst_buffer
        if job.id in self._burst_buffer_allocations:
            for burst_buffer_id in self._burst_buffer_allocations[job.id]:
                burst_buffer = self._burst_buffers[burst_buffer_id]
                burst_buffer.free(job)
            del self._burst_buffer_allocations[job.id]

    def _validate_job(self, job: Job) -> bool:
        if job.requested_resources > len(self.resources.compute):
            job.reject('Too few resources available in the system (overall)')
            self.reject_compute_resources += 1
            return False
        # Requested space for a single node must fit within single burst buffer.
        if job.profile.bb > self.platform.burst_buffer_capacity:
            job.reject('Too much requested burst buffer space for a single node.')
            self.reject_burst_buffer_capacity += 1
            return False
        # Number of how many times job.profile.bb could fit as a whole in total burst buffer
        # space.
        if job.requested_resources > (self.platform.burst_buffer_capacity // job.profile.bb) * \
                len(self._burst_buffers):
            job.reject('Too much total requested burst buffer space.')
            self.reject_total_burst_buffer += 1
            return False
        return True

    def _create_ordered_compute_resource_ids(self):
        """Creates a list of compute resource ids ordered according to Dragonfly topology."""
        self._ordered_compute_resource_ids = []
        num_nodes_in_chassis = self.platform.num_routers * self.platform.num_nodes_per_router
        for node_id in range(self.platform.num_all_nodes):
            if node_id % num_nodes_in_chassis == 0:
                # This is a storage node
                continue
            for compute_resource in self.resources.compute:
                curr_node_id = self.get_node_id(compute_resource.name)
                if curr_node_id == node_id:
                    self._ordered_compute_resource_ids.append(compute_resource.id)
                    break
        assert len(self._ordered_compute_resource_ids) == \
               self.platform.num_all_nodes - self.platform.num_burst_buffers

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

    def _create_resource_filter(self) -> Callable[..., List[Resource]]:
        # Based on do_filter function from generate_resources_filter in algorithms/utils.py
        def do_filter(
                resources: List[Resource],
                job: Job,
                current_time: float,
                max_entries: int,
                min_entries: int,
                **kwargs
        ):
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
                        result_set.insert(*ProcSet(interval)[:min_entries - len(result_set)])
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
    def get_node_id(node_name: ResourceName):
        """Gets platform node id from the name in the platform file.
        For 'node_42' will return 42.
        """
        return ResourceId(int(node_name.split('_')[-1]))


class PlanBasedAnnealer(Annealer):
    """State is a tuple (job_permutation, execution_plan)."""
    updates = 0

    def __init__(self, state, scheduler, score_function):
        super().__init__(state)
        self.scheduler: AllocOnlyScheduler = scheduler
        self.score_function = score_function

    def move(self):
        jobs, _ = self.state
        remove_index = randint(0, len(jobs) - 1)
        insert_index = randint(0, len(jobs) - 2)
        jobs.insert(insert_index, jobs.pop(remove_index))
        plan, allocations = self.scheduler.create_execution_plan(jobs)
        self.scheduler.free_allocations(allocations)
        self.state = jobs, plan

    def energy(self):
        _, plan = self.state
        return self.score_function(plan)

    def copy_state(self, state):
        jobs, plan = state
        return jobs[:], plan

    def update(self, *args, **kwargs):
        pass
