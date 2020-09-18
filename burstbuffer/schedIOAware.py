from .io_aware import IOAwareScheduler


class SchedIOAware(IOAwareScheduler):
    def schedule(self):
        if not self.allow_schedule:
            return
        # TODO: add a list of static jobs to scheduler
        jobs = self.jobs.static_job.runnable
        if self.algorithm == 'filler':
            self.filler_schedule(jobs=jobs, abort_on_first_nonfitting=False)
        elif self.algorithm == 'fcfs':
            self.filler_schedule(jobs=jobs, abort_on_first_nonfitting=True)
        elif self.algorithm == 'backfill':
            self.backfill_schedule(
                jobs=jobs, backfilling_reservation_depth=self.backfilling_reservation_depth)
        else:
            assert False
