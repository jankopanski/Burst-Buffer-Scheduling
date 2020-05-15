from burstbuffer.alloc_only import AllocOnlyScheduler


class BackfillAllocOnlyScheduler(AllocOnlyScheduler):
    def schedule(self):
        self._backfill_schedule()
