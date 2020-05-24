from burstbuffer.alloc_only import AllocOnlyScheduler


class BackfillAllocOnlyScheduler(AllocOnlyScheduler):
    def __init__(self, options):
        super().__init__(options)
        self.backfilling_reservation_depth = options['backfill']

    def schedule(self):
        self._backfill_schedule(backfilling_reservation_depth=self.backfilling_reservation_depth)
