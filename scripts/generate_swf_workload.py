#!/usr/bin/env python3
# ./scripts/generate_swf_workload.py platforms/dragonfly96.yaml workloads/swf.yaml workloads/swf/KTH-SP2-1996-2.1-cln.swf workloads/KTH-SP2-1996-2.1-cln-1000-1.json

from argparse import ArgumentParser
from os.path import basename, splitext

from burstbuffer.platform import Platform, read_config
from burstbuffer.model import WorkloadModel
from burstbuffer.constants import MB
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
num_ignored_jobs = 0
storage_intervals = set()

first_submit_time = None
with open(args.input_file) as input_file:
    for line in input_file:
        # Check if enough jobs were already processed
        if model.num_jobs and len(jobs) + num_ignored_jobs == model.num_jobs:
            break

        job = SWFJob.parse_line(line)
        # Skip comment lines and first N jobs.
        if not job or job.job_number < workload_config['from_job_number']:
            continue
        # Ignore jobs with missing data in SWF file.
        if job.job_number <= 0 or job.submit_time <= 0 or job.requested_time <= 0 or \
                job.run_time <= 0 or job.requested_processors <= 0:
            num_ignored_jobs += 1
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
        # Assign minimal burst buffer request to a very short jobs (120 seconds).
        # Alternatively 0 burst buffer could be specified as a requests, but current simulation
        # model requires a non 0 burst buffer.
        if job.requested_time <= 120:
            burst_buffer = 10 * MB
            computations = job.run_time * platform.cpu_speed
        else:
            burst_buffer = model.generate_burst_buffer_lognorm(job.requested_processors)
            computations = round(platform.cpu_speed * max(
                job.run_time - model.multiply_factor_runtime * burst_buffer / platform.bandwidth,
                job.run_time * 0.05))
        # Ensure that there are no jobs that could have the same storage interval representation in
        # a StorageResource. Just a technical correction, does not influence the model.
        while (entry := (job.requested_time, burst_buffer)) in storage_intervals:
            burst_buffer -= 1
        storage_intervals.add(entry)
        communication = 0 if job.requested_processors == 1 else model.generate_communication()
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
print('Ignored {} jobs'.format(num_ignored_jobs))
