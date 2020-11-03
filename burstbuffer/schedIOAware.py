from operator import attrgetter

from .io_aware import IOAwareScheduler


class SchedIOAware(IOAwareScheduler):
    def schedule(self):
        if not self.allow_schedule:  # Performance optimisation
            return
        # TODO: add a list of static jobs to scheduler
        jobs = self.jobs.static_job.runnable
        if self.algorithm == 'filler':
            if self.priority_policy == 'sjf':
                jobs = jobs.sorted(attrgetter('requested_time'))
            self.filler_schedule(jobs=jobs, abort_on_first_nonfitting=False)
        elif self.algorithm == 'fcfs':
            self.filler_schedule(jobs=jobs, abort_on_first_nonfitting=True)
        elif self.algorithm == 'backfill':
            self.backfill_schedule(
                jobs=jobs,
                reservation_depth=self.backfilling_reservation_depth,
                future_burst_buffer_reservation=self.future_burst_buffer_reservation,
                priority_policy=self.priority_policy,
                balance_factor=self.balance_factor
            )
        elif self.algorithm == 'maxutil':
            self.maxutil_schedule(
                jobs=jobs,
                reservation_depth=self.backfilling_reservation_depth,
                balance_factor=self.balance_factor,
                optimisation=self.optimisation
            )
        elif self.algorithm == 'plan':
            self.plan_schedule(
                jobs=jobs,
                reservation_depth=self.backfilling_reservation_depth,
                priority_policy=self.priority_policy,
                optimisation=self.optimisation
            )
        elif self.algorithm == 'window':
            self.window_schedule(jobs=jobs, max_window_size=self.window_size)
        else:
            assert False
