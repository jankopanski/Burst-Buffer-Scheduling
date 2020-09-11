from typing import NewType

ResourceId = NewType('ResourceId', int)
ComputeResourceId = NewType('ComputeResourceId', ResourceId)
StorageResourceId = NewType('StorageResourceId', ResourceId)
ResourceName = NewType('ResourceName', str)
JobId = NewType('JobId', int)
PlatformNodeId = NewType('PlatformNodeId', int)
