"""
    schedFcfs
    ~~~~~~~~~

    Simple fcfs algoritihm using the pre-defined algorithm of the new scheduler api.

"""

from typing import Optional, Dict, List
from batsim.sched.resource import Resource, Resources
from batsim.sched.alloc import Allocation
from batsim.sched.scheduler import Scheduler
from batsim.sched.algorithms.filling import filler_sched
from batsim.sched.algorithms.utils import consecutive_resources_filter


class StorageResource(Resource):
    def __init__(
            self,
            scheduler: Scheduler,
            name: str,
            id: int,
            resources_list: Resources = None,
            capacity_bytes: int = 0):
        super().__init__(scheduler, name, id, resources_list,
                         resource_sharing=True)
        self._capacity = capacity_bytes
        self._available_space = capacity_bytes
        self._allocations: Dict[Allocation, int] = {}  # allocation -> num_bytes

    @property
    def available_space(self):
        return self._available_space

    @available_space.setter
    def available_space(self, num_bytes: int):
        assert num_bytes >= 0
        self._available_space = num_bytes

    def allocate(self, num_bytes: int, allocation: Allocation):
        assert allocation not in self._allocations
        self.available_space -= num_bytes
        self._allocations[allocation] = num_bytes

    def free(self, allocation: Allocation):
        self.available_space += self._allocations[allocation]
        del self._allocations[allocation]

    def find_first_time_to_fit_job(self, job, time=None,
                                   future_reservation=False):
        raise NotImplementedError('Later')


# Only allocates burst buffers without executing any data transfers to burst buffers
# class BaseAllocOnlyScheduler(Scheduler):

# Convention
# node_id is an id of the node from the platform file. It is extracted from the name.
# id is an integer assigned by Batsim to a node.
# There exists a mapping between ids and node_ids.
class MySchedFcfs(Scheduler):
    BURST_BUFFER_CAPACITY_GB = 1
    NUM_GROUPS, NUM_CHASSIS, NUM_ROUTERS, NUM_NODES_PER_ROUTER = 3, 2, 3, 2
    BURST_BUFFER_CAPACITY_BYTES = BURST_BUFFER_CAPACITY_GB * 10 ** 9
    NUM_NODES = NUM_GROUPS * NUM_CHASSIS * NUM_ROUTERS * NUM_NODES_PER_ROUTER
    NUM_BURST_BUFFERS = NUM_GROUPS * NUM_CHASSIS

    def __init__(self, options={}):
        super().__init__(options=options)
        self._pfs_id: int
        self._burst_buffers = Resources()
        # compute_node_id -> [chassis_bb_id, group_bb_id, all_bb_id]
        self._burst_buffer_proximity: Dict[int, List[List[int]]]

    def on_init(self):
        self._print_node_mapping()
        # Storage machines are all burst buffers hosts plus pfs host.
        assert len(self.machines['storage']) - 1 == self.NUM_BURST_BUFFERS
        assert len(self.machines['storage']) - 1 + len(self.machines['compute']) == self.NUM_NODES
        for storage_resource in self.machines['storage']:
            if storage_resource['name'] == 'pfs':
                self._pfs_id = storage_resource['id']
            else:
                self._burst_buffers.add(StorageResource(
                    self,
                    id=storage_resource['id'],
                    name=storage_resource['name'],
                    resources_list=self._burst_buffers))
        self._create_burst_buffer_proximity()

    def schedule(self):
        print("MySchedFcfs schedule")
        MySchedFcfsFun(self)

    def _create_burst_buffer_proximity(self):
        """Compute resource id to burst buffer id proximity mapping for the Dragonfly topology."""
        self._burst_buffer_proximity = {compute.id: [[], [], []] for compute in
                                        self.resources.compute}
        # Assume that there is one burst buffer node in every chassis
        num_nodes_in_chassis = self.NUM_ROUTERS * self.NUM_NODES_PER_ROUTER
        num_nodes_in_group = num_nodes_in_chassis * self.NUM_CHASSIS
        burst_buffer_node_id_to_id = {self._get_node_id(bb.name): bb.id for bb in
                                      self._burst_buffers}
        assert all([bb_node_id % num_nodes_in_chassis == 0 for bb_node_id in
                    burst_buffer_node_id_to_id.keys()])

        for compute_resource in self.resources.compute:
            node_id = self._get_node_id(compute_resource.name)
            chassis_bb_node_id = (node_id // num_nodes_in_chassis) * num_nodes_in_chassis
            self._burst_buffer_proximity[compute_resource.id][0] = \
                [burst_buffer_node_id_to_id[chassis_bb_node_id]]

            first_bb_node_id_in_group = (node_id // num_nodes_in_group) * num_nodes_in_group
            for bb_node_id in range(first_bb_node_id_in_group,
                                    first_bb_node_id_in_group + num_nodes_in_group,
                                    num_nodes_in_chassis):
                if bb_node_id != chassis_bb_node_id:
                    self._burst_buffer_proximity[compute_resource.id][1].append(
                        burst_buffer_node_id_to_id[bb_node_id])

            self._burst_buffer_proximity[compute_resource.id][2] = \
                list(set(burst_buffer_node_id_to_id.values()) -
                     set(self._burst_buffer_proximity[compute_resource.id][0]) -
                     set(self._burst_buffer_proximity[compute_resource.id][1]))

    def _print_node_mapping(self):
        for node in self.machines['compute']:
            print('compute node: {} -> {}'.format(node['name'], node['id']))
        for node in self.machines['storage']:
            print('storage node: {} -> {}'.format(node['name'], node['id']))

    @staticmethod
    def _get_node_id(node_name):
        """Gets platform node id from the name in the platform file."""
        return int(node_name.split('_')[-1])


def MySchedFcfsFun(scheduler):
    return filler_sched(
        scheduler,
        resources_filter=consecutive_resources_filter,
        abort_on_first_nonfitting=True)
