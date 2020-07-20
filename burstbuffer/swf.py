from typing import Optional
from batsim.sched.workloads.models.generator import JobModelData


class SWFJob(JobModelData):
    FIELDS = [
        "job_number",
        "submit_time",
        "wait_time",
        "run_time",
        "used_processors",
        "average_cpu_time",
        "used_memory",
        "requested_processors",
        "requested_time",
        "requested_memory",
        "completed",
        "user_id",
        "group_id",
        "application",
        "queue",
        "partition",
        "preceding_job",
        "think_time",
    ]

    def __init__(self, swf_record):
        kwargs = {name: value for name, value in zip(self.FIELDS, swf_record)}
        super().__init__(**kwargs)

    @staticmethod
    def parse_line(line) -> Optional['SWFJob']:
        line = line.strip()
        if line.startswith(';'):
            return None
        swf_record = []
        for field in line.split():
            try:
                swf_record.append(int(float(field)))
            except ValueError:
                swf_record.append(-1)
        assert len(swf_record) == len(SWFJob.FIELDS)
        return SWFJob(swf_record)
