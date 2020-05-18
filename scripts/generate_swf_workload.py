import os.path
import yaml

from batsim.sched.workloads.workloads import JobDescription, WorkloadDescription
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


class SWFWorkloadGenerator:
    def __init__(self, input_file, platform_config, workload_config):
        name = os.path.basename(input_file).split('.')[0]
        self.platform = yaml.load(platform_config)
        self.workload = WorkloadDescription(name=name)
