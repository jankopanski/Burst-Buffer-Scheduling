from .alloc_only import AllocOnlyScheduler


class SchedAllocOnly(AllocOnlyScheduler):
    def schedule(self):
        if self.algorithm == 'filler':
            self.filler_schedule(abort_on_first_nonfitting=False)
        elif self.algorithm == 'fcfs':
            self.filler_schedule(abort_on_first_nonfitting=True)
        elif self.algorithm == 'backfill':
            self.backfill_schedule(
                reservation_depth=self.backfilling_reservation_depth,
                future_burst_buffer_reservation=self.future_burst_buffer_reservation,
                priority_policy=self.priority_policy,
                balance_factor=self.balance_factor
            )
        elif self.algorithm == 'moo':
            self.moo_schedule()
        elif self.algorithm == 'maxutil':
            self.maxutil_schedule(
                reservation_depth=self.backfilling_reservation_depth,
                balance_factor=self.balance_factor,
                optimisation=self.optimisation
            )
        elif self.algorithm == 'plan':
            self.plan_schedule(
                reservation_depth=self.backfilling_reservation_depth,
                priority_policy=self.priority_policy,
                optimisation=self.optimisation
            )
        elif self.algorithm == 'window':
            self.window_schedule(
                jobs=self.jobs.runnable,
                max_window_size=self.window_size,
                reservation_depth=self.backfilling_reservation_depth,
                optimisation=self.optimisation
            )
        else:
            assert False
