from yaml import safe_load

from .constants import GFLOPS, MB, GB


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
        self.num_groups = config['num_groups']
        self.num_chassis = config['num_chassis']
        self.num_routers = config['num_routers']
        self.num_nodes_per_router = config['num_nodes_per_router']
        self.num_all_nodes = self.num_groups * self.num_chassis * \
                             self.num_routers * self.num_nodes_per_router
        self.num_burst_buffers = self.num_groups * self.num_chassis
        self.total_burst_buffer_capacity = self.burst_buffer_capacity * self.num_burst_buffers
