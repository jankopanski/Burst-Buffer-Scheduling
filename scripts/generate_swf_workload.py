#!/usr/bin/env python3
from os.path import basename, splitext
from argparse import ArgumentParser

from batsim.sched.workloads.models.generator import JobModelData

from burstbuffer.model import Platform, WorkloadModel, read_config


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


parser = ArgumentParser()
parser.add_argument('platform_config_file', help='yaml')
parser.add_argument('workload_config_file', help='yaml')
parser.add_argument('input_file', help='Parallel Workload Achieve swf file')
parser.add_argument('output_file', help='Batsim json file')
args = parser.parse_args()

platform_config = read_config(args.platform_config_file)
workload_config = read_config(args.workload_config_file)
platform = Platform(platform_config)
model = WorkloadModel(workload_config, platform)

jobs = []
profiles = {}

num_jobs = 0
first_submit_time = None
with open(args.input_file) as input_file:
    for line in input_file:
        if model.num_jobs and num_jobs == model.num_jobs:
            break

        line = line.strip()
        if line.startswith(';'):
            continue
        swf_record = [int(x) for x in line.split()]
        job = SWFJob(swf_record)
        num_jobs += 1

        # Ignore time before first submitted job.
        if not first_submit_time:
            # -1 to match pybatsim scheduler time update.
            first_submit_time = job.submit_time - 1
        submit_time = job.submit_time - first_submit_time

        profile_id = str(job.job_number)
        computations = job.run_time * platform.cpu_speed
        communication = 0 if job.requested_processors == 1 else model.generate_communication()
        burst_buffer = model.generate_burst_buffer()
        jobs.append(model.generate_job(job.job_number,
                                       submit_time,
                                       job.requested_time,
                                       job.requested_processors,
                                       profile_id))
        profiles[profile_id] = model.generate_profile(computations, communication, burst_buffer)

name = splitext(basename(args.input_file))[0]
description = '{} jobs'.format(num_jobs)
model.save_workload(args.output_file, name, description, platform.nb_res, jobs, profiles)