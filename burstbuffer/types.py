from typing import NewType, Dict, List, Tuple
from batsim.sched import Job, ComputeResource

ResourceId = NewType('ResourceId', int)
ComputeResourceId = NewType('ComputeResourceId', ResourceId)
StorageResourceId = NewType('StorageResourceId', ResourceId)
ResourceName = NewType('ResourceName', str)
JobId = NewType('JobId', int)
PlatformNodeId = NewType('PlatformNodeId', int)

from .storage import StorageResource
# (job, start_time, compute_resources, burst_buffers)
ExecutionPlan = List[
    Tuple[Job, float, List[ComputeResource], Dict[ComputeResource, StorageResource]]]
