from burstbuffer.alloc_only import AllocOnlyScheduler


class FillerAllocOnlyScheduler(AllocOnlyScheduler):
    def schedule(self):
        self._filler_schedule(abort_on_first_nonfitting=False)
