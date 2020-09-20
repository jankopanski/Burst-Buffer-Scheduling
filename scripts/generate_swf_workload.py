#!/usr/bin/env python3
# ./scripts/generate_swf_workload.py platforms/dragonfly96.yaml workloads/swf.yaml workloads/swf/KTH-SP2-1996-2.1-cln.swf workloads/KTH-SP2-1996-2.1-cln-1000-1.json

from argparse import ArgumentParser
from os.path import basename, splitext

from burstbuffer.model import Platform, WorkloadModel, read_config
from burstbuffer.swf import SWFJob


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
first_job_number = None
last_job_number = None

first_submit_time = None
with open(args.input_file) as input_file:
    for line in input_file:
        # Check if enough jobs were already processed
        if model.num_jobs and len(jobs) == model.num_jobs:
            break

        job = SWFJob.parse_line(line)
        if not job or job.job_number < workload_config['from_job_number']:
            continue

        # Ignore time before first submitted job.
        if not first_submit_time:
            # -1 to match pybatsim scheduler time update. Pybatsim crashes without it.
            # Could be a smaller epsilon.
            first_submit_time = job.submit_time - 1
            first_job_number = job.job_number
        submit_time = job.submit_time - first_submit_time
        last_job_number = job.job_number

        profile_id = str(job.job_number)
        computations = job.run_time * platform.cpu_speed
        communication = 0 if job.requested_processors == 1 else model.generate_communication()
        burst_buffer = model.generate_burst_buffer_lognorm(job.requested_processors)
        jobs.append(model.generate_job(job.job_number,
                                       submit_time,
                                       job.requested_time,
                                       job.requested_processors,
                                       profile_id))
        profiles[profile_id] = model.generate_profile(computations, communication, burst_buffer)

name = splitext(basename(args.input_file))[0]
description = '{} jobs from swf job number {} to {} inclusive'.format(
    len(jobs), first_job_number, last_job_number)
model.save_workload(args.output_file, name, description, platform.nb_res, jobs, profiles)