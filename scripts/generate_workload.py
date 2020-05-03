#!/usr/bin/env python3

import math
from random import gauss, lognormvariate, weibullvariate, expovariate
from json import dump

output_file = '../workloads/generated_cluster30_jobs200.json'

# Constants
GFLOPS = 10**9
MB = 10**6
GB = MB*10**3

# Platform parameters
NB_RES = 30
CPU_SPEED = 1 * GFLOPS
BANDWIDTH = 125 * MB  # 1000 Mbps
BURST_BUFFER_CAPACITY_GB = 2
BURST_BUFFER_CAPACITY = BURST_BUFFER_CAPACITY_GB * GB

# Interval times between jobs according to Weibull distribution.
# Time in seconds
# Scale
TIME_DISTRIBUTION_LAMBDA = 100
# Shape
TIME_DISTRIBUTION_K = 1.5

# Workload parameters
NUM_JOBS = 200
# Nodes per job
EXPECTED_LOG_NUM_NODES = 0.8
STDDEV_LOG_NUM_NODES = 1
# Flops
EXPECTED_COMPUTATIONS_PER_NODE = 5 * GFLOPS
STDDEV_COMPUTATIONS_PER_NODE = EXPECTED_COMPUTATIONS_PER_NODE * 0.2
LAMBDA_SCALE_COMPUTATIONS_PER_NODE = 0.5
MULTIPLY_FACTOR_COMPUTATIONS_PER_NODE = 10 * GFLOPS
# Bytes. Note that platform bandwidth is given in Megabites/s
EXPECTED_COMMUNICATION_PER_NODE = 10 * GB
STDDEV_COMMUNICATION_PER_NODE = EXPECTED_COMMUNICATION_PER_NODE * 0.2
# Bytes
EXPECTED_BURST_BUFFER_PER_NODE = 1 * GB
STDDEV_BURST_BUFFER_PER_NODE = EXPECTED_BURST_BUFFER_PER_NODE * 0.2
# How much is walltime overestimated
MULTIPLY_FACTOR_WALLTIME = 3
STDDEV_WALLTIME = 0.1

print('Expected num nodes: ', math.e**(EXPECTED_LOG_NUM_NODES+STDDEV_LOG_NUM_NODES**2/2))
print('Expected time interval: ', TIME_DISTRIBUTION_LAMBDA*math.gamma(1+1/TIME_DISTRIBUTION_K))


def generate_num_nodes() -> int:
    return min(NB_RES, max(1, round(lognormvariate(EXPECTED_LOG_NUM_NODES, STDDEV_LOG_NUM_NODES))))


def generate_computations() -> int:
    return round(gauss(EXPECTED_COMPUTATIONS_PER_NODE, STDDEV_COMPUTATIONS_PER_NODE))


def generate_computations_exponential(num_nodes: int) -> int:
    computations = expovariate(LAMBDA_SCALE_COMPUTATIONS_PER_NODE * num_nodes / NB_RES) * \
                   MULTIPLY_FACTOR_COMPUTATIONS_PER_NODE
    return round(computations)

# TODO: Increase communication with the number of nodes
def generate_communication() -> int:
    return round(gauss(EXPECTED_COMMUNICATION_PER_NODE, STDDEV_COMMUNICATION_PER_NODE))


def generate_burst_buffer() -> int:
    return round(min(gauss(EXPECTED_BURST_BUFFER_PER_NODE, STDDEV_BURST_BUFFER_PER_NODE),
                     BURST_BUFFER_CAPACITY))


def estimate_running_time(num_nodes: int, computations: int, communication: int) -> float:
    return max(computations / CPU_SPEED, num_nodes * communication / BANDWIDTH)


def generate_walltime(estimated_running_time: float) -> int:
    expected_walltime = estimated_running_time * MULTIPLY_FACTOR_WALLTIME
    return round(max(gauss(expected_walltime, STDDEV_WALLTIME), estimated_running_time * 2))

jobs = []
profiles = {}
release_time = 0

for i in range(NUM_JOBS):
    release_time += math.ceil(weibullvariate(TIME_DISTRIBUTION_LAMBDA, TIME_DISTRIBUTION_K))
    num_nodes = generate_num_nodes()
    # computations = generate_computations()
    computations = generate_computations_exponential(num_nodes)
    communication = generate_communication()
    burst_buffer = generate_burst_buffer()  # per node
    walltime = generate_walltime(estimate_running_time(num_nodes, computations, communication))
    profile_id = str(i)
    job = {
        'id': i,
        'subtime': release_time,
        'walltime': walltime,
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
    'LAMBDA_SCALE_COMPUTATIONS_PER_NODE': LAMBDA_SCALE_COMPUTATIONS_PER_NODE,
    'MULTIPLY_FACTOR_COMPUTATIONS_PER_NODE': MULTIPLY_FACTOR_COMPUTATIONS_PER_NODE,
    'EXPECTED_COMMUNICATION_PER_NODE': EXPECTED_COMMUNICATION_PER_NODE,
    'STDDEV_COMMUNICATION_PER_NODE': STDDEV_COMMUNICATION_PER_NODE,
    'EXPECTED_BURST_BUFFER_PER_NODE': EXPECTED_BURST_BUFFER_PER_NODE,
    'STDDEV_BURST_BUFFER_PER_NODE': STDDEV_BURST_BUFFER_PER_NODE,
    'MULTIPLY_FACTOR_WALLTIME': MULTIPLY_FACTOR_WALLTIME,
    'STDDEV_WALLTIME': STDDEV_WALLTIME,
}

workload = {
    'parameters': params,
    'nb_res': NB_RES,
    'jobs': jobs,
    'profiles': profiles
}

dump(workload, open(output_file, 'w'), indent=2)
