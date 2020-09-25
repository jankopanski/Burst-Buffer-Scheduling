import math
from random import gauss, expovariate, lognormvariate, weibullvariate
from json import dump
from yaml import safe_load

from scipy import stats

# Constants
GFLOPS = 10**9
MB = 10**6
GB = MB*1000
KiB = 1024


def read_config(config_file):
    with open(config_file) as f:
        return safe_load(f)


class Platform:
    def __init__(self, config):
        # Platform parameters
        self.nb_res = config['nb_res']  # Number of compute resources
        self.cpu_speed = config['cpu_speed'] * GFLOPS
        self.bandwidth = config['bandwidth'] * MB  # 1000 Mbps
        self.burst_buffer_capacity = config['burst_buffer_capacity'] * GB
        self.total_burst_buffer_capacity = self.burst_buffer_capacity * self.nb_res
        self.num_groups = config['num_groups']
        self.num_chassis = config['num_chassis']
        self.num_routers = config['num_routers']
        self.num_nodes_per_router = config['num_nodes_per_router']
        self.num_nodes = self.num_groups * self.num_chassis * \
                         self.num_routers * self.num_nodes_per_router
        self.num_burst_buffers = self.num_groups * self.num_chassis


class WorkloadModel:
    def __init__(self, config, platform):
        self.platform = platform
        # Number of jobs to generate
        self.num_jobs = config['num_jobs']
        # Interval times between jobs according to Weibull distribution.
        # Time in seconds
        # Scale
        self.time_distribution_lambda = config['time_distribution_lambda']
        # Shape
        self.time_distribution_k = config['time_distribution_k']
        # Nodes per job
        self.expected_log_num_nodes = config['expected_log_num_nodes']
        self.stddev_log_num_nodes = config['stddev_log_num_nodes']
        # Flops
        self.expected_computations_per_node = \
            config['expected_computations_per_node'] * GFLOPS
        self.stddev_computations_per_node = \
            self.expected_computations_per_node * config['stddev_computations_per_node']
        self.lambda_scale_computations_per_node = config['lambda_scale_computations_per_node']
        self.multiply_factor_computations_per_node = \
            config['multiply_factor_computations_per_node'] * GFLOPS
        # Bytes. Note that platform bandwidth is given in Megabites/s
        self.expected_communication_per_node = config['expected_communication_per_node'] * GB
        self.stddev_communication_per_node = \
            self.expected_communication_per_node * config['stddev_communication_per_node']
        # Bytes
        self.expected_burst_buffer_per_node = config['expected_burst_buffer_per_node'] * GB
        self.stddev_burst_buffer_per_node = \
            self.expected_burst_buffer_per_node * config['stddev_burst_buffer_per_node']
        # How much is walltime overestimated
        self.multiply_factor_walltime = config['multiply_factor_walltime']
        self.stddev_walltime = 1 * config['stddev_walltime']
        self.multiply_factor_runtime = config['multiply_factor_runtime']

        self.burst_buffer_distribution = stats.lognorm(
            s=1.0972516604048774,
            loc=-150361.59523836235,
            scale=2714115.5724594607
        )

    def next_submit_time(self, prev_submit_time) -> int:
        time_delta = math.ceil(weibullvariate(self.time_distribution_lambda,
                                              self.time_distribution_k))
        return prev_submit_time + time_delta

    def generate_num_nodes(self) -> int:
        return min(self.platform.nb_res, max(1, round(lognormvariate(self.expected_log_num_nodes,
                                                                     self.stddev_log_num_nodes))))

    def generate_computations(self) -> int:
        return round(gauss(self.expected_computations_per_node, self.stddev_computations_per_node))

    def generate_computations_exponential(self, num_nodes: int) -> int:
        computations = expovariate(
            self.lambda_scale_computations_per_node * num_nodes / self.platform.nb_res) * \
            self.multiply_factor_computations_per_node
        return round(computations)

    # TODO: Decrease communication with the number of nodes
    def generate_communication(self) -> int:
        return round(gauss(self.expected_communication_per_node,
                           self.stddev_communication_per_node))

    def generate_burst_buffer(self) -> int:
        return round(min(gauss(self.expected_burst_buffer_per_node,
                               self.stddev_burst_buffer_per_node),
                         self.platform.burst_buffer_capacity))

    def generate_burst_buffer_increasing_std(self, num_nodes) -> int:
        return round(min(gauss(
            self.expected_burst_buffer_per_node,
            self.stddev_burst_buffer_per_node * (1 + num_nodes / self.platform.num_nodes)),
            self.platform.burst_buffer_capacity))

    def generate_burst_buffer_lognorm(self, num_nodes) -> int:
        """
        Generates burst buffer requirements in bytes per processor.
        Adjust the requirements to always fit into a platform total capacity.
        """
        # Set the lower bound to 100 MB per processor. About 1.5% of jobs will be assigned the lower
        # bound.
        burst_buffer_bytes_per_proc = round(max(
            self.burst_buffer_distribution.rvs() * KiB, 100 * MB))
        total_burst_buffer_bytes = min(burst_buffer_bytes_per_proc * num_nodes,
                                       self.platform.total_burst_buffer_capacity)
        requested_burst_buffer = round(total_burst_buffer_bytes / num_nodes)
        assert requested_burst_buffer > 0
        return requested_burst_buffer

    def estimate_running_time(self, num_nodes: int, computations: int, communication: int) -> float:
        return max(computations / self.platform.cpu_speed,
                   num_nodes * communication / self.platform.bandwidth)

    def generate_walltime(self, estimated_running_time: float) -> int:
        expected_walltime = estimated_running_time * self.multiply_factor_walltime
        return round(max(gauss(expected_walltime, self.stddev_walltime),
                         estimated_running_time * 2))

    @staticmethod
    def generate_profile(computations, communication, burst_buffer):
        return {
            'type': 'parallel_homogeneous',
            'cpu': computations,
            'com': communication,
            'bb': burst_buffer,
        }

    @staticmethod
    def generate_job(id, submit_time, walltime, num_nodes, profile_id):
        return {
            'id': id,
            'subtime': submit_time,
            'walltime': walltime,
            'res': num_nodes,
            'profile': str(profile_id),
        }

    @staticmethod
    def save_workload(output_file, name, description, nb_res, jobs, profiles):
        workload = {
            'name': name,
            'description': description,
            'nb_res': nb_res,
            'jobs': jobs,
            'profiles': profiles
        }
        dump(workload, open(output_file, 'w'), indent=2)
