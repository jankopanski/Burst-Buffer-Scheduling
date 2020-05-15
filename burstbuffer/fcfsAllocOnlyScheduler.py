from burstbuffer.alloc_only import AllocOnlyScheduler


class FcfsAllocOnlyScheduler(AllocOnlyScheduler):
    def schedule(self):
        self._filler_schedule()
