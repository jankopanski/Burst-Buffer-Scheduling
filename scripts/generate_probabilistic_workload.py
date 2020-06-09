#!/usr/bin/env python3
from argparse import ArgumentParser
from burstbuffer.model import Platform, WorkloadModel, read_config


parser = ArgumentParser()
parser.add_argument('platform_config_file')
parser.add_argument('workload_config_file')
parser.add_argument('output_file')
args = parser.parse_args()

platform_config = read_config(args.platform_config_file)
workload_config = read_config(args.workload_config_file)
platform = Platform(platform_config)
model = WorkloadModel(workload_config, platform)

jobs = []
profiles = {}
submit_time = 0

for i in range(model.num_jobs):
    submit_time = model.next_submit_time(submit_time)
    num_nodes = model.generate_num_nodes()
    # computations = generate_computations()
    computations = model.generate_computations_exponential(num_nodes)
    communication = model.generate_communication()
    burst_buffer = model.generate_burst_buffer()  # per node
    walltime = model.generate_walltime(
        model.estimate_running_time(num_nodes, computations, communication))
    profile_id = str(i)
    profiles[profile_id] = model.generate_profile(computations, communication, burst_buffer)
    jobs.append(model.generate_job(i, submit_time, walltime, num_nodes, profile_id))

name = 'Probabilistic workload'
description = ''
model.save_workload(args.output_file, name, description, platform.nb_res, jobs, profiles)