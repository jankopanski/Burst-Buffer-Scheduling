#!/usr/bin/env python3

import math
from random import gauss, lognormvariate, weibullvariate
from json import dump

output_file = '../workloads/generated_cluster128_jobs100.json'

# Constants
GFLOPS = 10**9
MB = 10**6
GB = MB*10**3

# Platform parameters
NB_RES = 128

# Interval times between jobs according to Weibull distribution.
# Time in seconds
# Scale
TIME_DISTRIBUTION_LAMBDA = 10
# Shape
TIME_DISTRIBUTION_K = 1.5

# Workload parameters
NUM_JOBS = 100
# Nodes per job
EXPECTED_LOG_NUM_NODES = 2
STDDEV_LOG_NUM_NODES = 1
# Flops
EXPECTED_COMPUTATIONS_PER_NODE = 100 * GFLOPS
STDDEV_COMPUTATIONS_PER_NODE = EXPECTED_COMPUTATIONS_PER_NODE * 0.2
# Bytes. Note that platform bandwidth is given in Megabites/s
EXPECTED_COMMUNICATION_PER_NODE = 10 * GB
STDDEV_COMMUNICATION_PER_NODE = EXPECTED_COMMUNICATION_PER_NODE * 0.2
# Bytes
EXPECTED_BURST_BUFFER_PER_NODE = 1 * GB
STDDEV_BURST_BUFFER_PER_NODE = EXPECTED_BURST_BUFFER_PER_NODE * 0.2

print('Expected num nodes: ', math.e**(EXPECTED_LOG_NUM_NODES+STDDEV_LOG_NUM_NODES**2/2))
print('Expected time interval: ', TIME_DISTRIBUTION_LAMBDA*math.gamma(1+1/TIME_DISTRIBUTION_K))


def generate_num_nodes():
    return min(NB_RES, max(1, round(lognormvariate(EXPECTED_LOG_NUM_NODES, STDDEV_LOG_NUM_NODES))))


def generate_computations():
    return round(gauss(EXPECTED_COMPUTATIONS_PER_NODE, STDDEV_COMPUTATIONS_PER_NODE))


# TODO: Increase communication with the number of nodes
def generate_communication():
    return round(gauss(EXPECTED_COMMUNICATION_PER_NODE, STDDEV_COMMUNICATION_PER_NODE))


def generate_burst_buffer():
    return round(gauss(EXPECTED_BURST_BUFFER_PER_NODE, STDDEV_BURST_BUFFER_PER_NODE))


jobs = []
profiles = {}
release_time = 0

for i in range(NUM_JOBS):
    release_time += math.ceil(weibullvariate(TIME_DISTRIBUTION_LAMBDA, TIME_DISTRIBUTION_K))
    num_nodes = generate_num_nodes()
    computations = generate_computations()
    communication = generate_communication()
    burst_buffer = generate_burst_buffer()
    profile_id = str(i)
    job = {
        'id': i,
        'subtime': release_time,
        'walltime': 1000,
        'res': num_nodes,
        'profile': profile_id,
    }
    profile = {
        'type': 'parallel_homogeneous',
        'cpu': computations,
        'com': communication,
        'bb': burst_buffer,
    }
    jobs.append(job)
    profiles[profile_id] = profile

params = {
    'NB_RES': NB_RES,
    'TIME_DISTRIBUTION_LAMBDA': TIME_DISTRIBUTION_LAMBDA,
    'TIME_DISTRIBUTION_K': TIME_DISTRIBUTION_K,
    'EXPECTED_COMPUTATIONS_PER_NODE': EXPECTED_COMPUTATIONS_PER_NODE,
    'STDDEV_COMPUTATIONS_PER_NODE': STDDEV_COMPUTATIONS_PER_NODE,
    'EXPECTED_COMMUNICATION_PER_NODE': EXPECTED_COMMUNICATION_PER_NODE,
    'STDDEV_COMMUNICATION_PER_NODE': STDDEV_COMMUNICATION_PER_NODE,
    'EXPECTED_BURST_BUFFER_PER_NODE': EXPECTED_BURST_BUFFER_PER_NODE,
    'STDDEV_BURST_BUFFER_PER_NODE': STDDEV_BURST_BUFFER_PER_NODE,
}

workload = {
    'parameters': params,
    'nb_res': NB_RES,
    'jobs': jobs,
    'profiles': profiles
}

dump(workload, open(output_file, 'w'), indent=2)
