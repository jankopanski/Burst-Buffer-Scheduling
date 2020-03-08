#!/usr/bin/env python

from xml.etree.ElementTree import ElementTree, Element
from add_disks import host_elem, disk_elem, link_elem

# tree = ElementTree()
# root = tree.parse("./two_nodes.xml")

num_nodes = 128
# num_nodes = 2000
cpu_speed = '1Gf'
# cpu_cores = 8
link_bandwidth = '1Gbps'
link_latency = '100us'
disk_read_bandwidth = '450MBps'
disk_write_bandwidth = '225MBps'
disk_latency = '500us'
every_ith_node = 4  # burst buffer is placed in every ith node


def basic_host_elem(host_id: str, speed: str) -> Element:
    elem = Element('host', {'id': host_id, 'speed': speed})
    return elem


# one link route
def basic_route_elem(src_id: str, dst_id: str, link_id: str, symmetrical='NO') -> Element:
    elem = Element('route', {
        'src': src_id, 'dst': dst_id, 'symmetrical': symmetrical})
    elem.append(Element('link_ctn', {'id': link_id}))
    return elem


platform = Element('platform', {'version': '4.1'})
zone = Element('zone', {'id': 'root_zone', 'routing': 'Full'})
platform.append(zone)

# Nodes
# master = host_elem('master', cpu_speed, cpu_cores)
master = basic_host_elem('master', cpu_speed)
master.append(Element('prop', {'id': 'role', 'value': 'master'}))
pfs = disk_elem('pfs')
zone.append(master)
zone.append(pfs)
for i in range(1, num_nodes + 1):
    # node = host_elem('host_' + str(i), cpu_speed, cpu_cores)
    node = basic_host_elem('host_' + str(i), cpu_speed)
    zone.append(node)
    if i % every_ith_node == 0:
        disk = disk_elem('host_' + str(i) + '_disk')
        zone.append(disk)

# Links
# master pfs
zone.append(link_elem('link_master_pfs', link_bandwidth, link_latency))
# master all
for i in range(1, num_nodes + 1):
    zone.append(link_elem('link_master_' + str(i), link_bandwidth, link_latency))
# pfs all
for i in range(1, num_nodes + 1):
    zone.append(link_elem('link_pfs_' + str(i), link_bandwidth, link_latency))
# all compute to all compute
for i in range(1, num_nodes + 1):
    for j in range(i + 1, num_nodes + 1):
        zone.append(link_elem('link_' + str(i) + '_' + str(j), link_bandwidth, link_latency))
# compute hosts to disks
for i in range(1, num_nodes + 1):
    if i % every_ith_node == 0:
        zone.append(link_elem('disk_' + str(i) + '_read', disk_read_bandwidth, disk_latency))
        zone.append(link_elem('disk_' + str(i) + '_write', disk_write_bandwidth, disk_latency))
# loopback
zone.append(Element('link', {
    'id': 'loopback',
    'bandwidth': link_bandwidth,
    'latency': '15us',
    'sharing_policy': 'FATPIPE'
}))

# Routes
# master loopback
zone.append(basic_route_elem('master', 'master', 'loopback', 'YES'))
# pfs loopback
zone.append(basic_route_elem('pfs', 'pfs', 'loopback', 'YES'))
# compute nodes loopback
for i in range(1, num_nodes + 1):
    zone.append(basic_route_elem('host_' + str(i), 'host_' + str(i), 'loopback', 'YES'))
# master all
for i in range(1, num_nodes + 1):
    zone.append(basic_route_elem('master', 'host_' + str(i), 'link_master_' + str(i), 'YES'))
# pfs all
for i in range(1, num_nodes + 1):
    zone.append(basic_route_elem('pfs', 'host_' + str(i), 'link_pfs_' + str(i), 'YES'))
# compute disks
for i in range(1, num_nodes + 1):
    if i % every_ith_node == 0:
        zone.append(basic_route_elem('host_' + str(i) + '_disk', 'host_' + str(i), 'disk_' + str(i) + '_read', 'NO'))
        zone.append(basic_route_elem('host_' + str(i), 'host_' + str(i) + '_disk', 'disk_' + str(i) + '_write', 'NO'))

tree = ElementTree(platform)
header = '''<?xml version='1.0'?>
<!DOCTYPE platform SYSTEM "http://simgrid.gforge.inria.fr/simgrid/simgrid.dtd">'''
with open("./output.xml", 'wb') as f:
    f.write(header.encode('utf8'))
    tree.write(f, 'utf-8', xml_declaration=False)