#!/usr/bin/env python

"""
Script for creating batsim workloads from Parallel Workload Archive
"""

from sys import argv
from os.path import splitext
from json import dump
from random import randint

# SWF parameters
COLS = [
        'job_number',
        'submit_time',
        'wait_time',
        'run_time',
        'allocated_processors',
        'average_cpu_time_used',
        'used_memory',
        'requested_processors',
        'requested_time',
        'requested_memory',
        'status',
        'user_id',
        'group_id',
        'application_number',
        'queue_number',
        'partition_number',
        'preceding_job_number',
        'think_time']
COL_NUM = dict(zip(COLS, range(len(COLS))))
# the following fields must be > 0
FIELDS = ['job_number',
          'submit_time',
          'requested_time',
          'requested_processors',
          'run_time']
          # 'requested_memory']
MIN_RUN_TIME = 60  # minimal job run time
MAX_RUN_TIME = 6000

# platform parameters
FLOPS = 10**9
BB_CAPACITY_GB = 256
BB_CAPACITY = BB_CAPACITY_GB * 10**9
NB_RES = 128
# nb_res = 0
# nb_res = 2000

# workload parameters
input_path = argv[1]
jobs = []
profiles = {}
MAX_JOBS = 10
num_jobs = 0
num_jobs_rejected = 0
min_submit_time = -1

with open(input_path, 'r') as file:
    for line in file:
        line = line.strip()
        if not line or line.startswith(';'):
            continue

        cols = [int(x) for x in line.split()]
        cols = dict([(name, cols[num]) for name, num in COL_NUM.items()])

        if not all([cols[field] > 0 for field in FIELDS]):
            num_jobs_rejected += 1
            continue
        if cols['requested_processors'] > NB_RES:
            num_jobs_rejected += 1
            continue
        if not MIN_RUN_TIME <= cols['run_time'] <= MAX_RUN_TIME:
            num_jobs_rejected += 1
            continue

        if min_submit_time < 0:
            min_submit_time = cols['submit_time']
        cols['submit_time'] = cols['submit_time'] - min_submit_time

        num_nodes = cols['requested_processors']
        requires_bb = randint(0, 3) > 0
        requested_memory = randint(1, num_nodes * BB_CAPACITY_GB / 4) * 10**9 if requires_bb else 0
        # requested_memory = 1
        # requested_memory = randint(1, 2 * num_nodes * BB_CAPACITY) // 10 ** 9 if requires_bb else 0

        job_id = cols['job_number']
        profile_id = 'p' + str(cols['job_number'])

        jobs.append({
            'id': job_id,
            'subtime': cols['submit_time'],
            'walltime': cols['requested_time'],
            'res': cols['requested_processors'],
            'profile': profile_id
        })
        profiles[profile_id] = {
            'type': 'parallel_homogeneous',
            'cpu': cols['run_time'] * FLOPS,
            'com': 0,
            'bb': requested_memory
            # 'bb': cols['requested_memory']
        }
        num_jobs += 1
        if MAX_JOBS and num_jobs >= MAX_JOBS:
            break
        # nb_res = max(nb_res, cols['requested_processors'])


# jobs = [{k: str(v) for k, v in j.items()} for j in jobs]
# profiles = {j: {k: str(v) for k, v in p.items()} for j, p in profiles.items()}

workload = {
    'nb_res': NB_RES,
    'jobs': jobs,
    'profiles': profiles
}
output_path = splitext(input_path)[0] + '.json'
with open(output_path, 'w') as output:
    dump(workload, output)