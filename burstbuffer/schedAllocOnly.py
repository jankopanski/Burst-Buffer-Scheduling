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
                balance_priority_policy=self.balance_priority_policy
            )
        else:
            assert False
