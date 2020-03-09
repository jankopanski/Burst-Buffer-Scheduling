#!/usr/bin/env python3
'''
This script add Batsim storage to existing host based Simgrid platforms.

Batsim storage is a Simgrid host with a speed of zero, the storage property.

For the DFS variant, it adds a storage for each hosts in the platform and a
link to the attached host. Each disk is named regarding the host it is attached
to with this pattern: "<HOST_ID>_disk"

For the PFS variant, it adds only one storage in the platform and links it to
each host assuming the has 2 links with this pattern: "<HOST_ID>_UP" and
"<HOST_ID>_DOWN". The storage is named "pfs" by default.

**WARNING**: It only works for "<hosts>" element and "Full" routing
'''

from xml.etree.ElementTree import ElementTree, Element
from typing import List


def disk_elem(disk_id: str) -> Element:
    elem = Element('host', { 'id': disk_id, 'speed': '0'})
    elem.append(Element(
        'prop', {'id': 'role', 'value': 'storage'}))
    return elem


def host_elem(host_id: str, speed: str, core: int) -> Element:
    elem = Element('host', { 'id': host_id, 'speed': speed, 'core': str(core)})
    return elem


def route_elem(src_id: str, dst_id: str, link_ids: List[str], symmetrical='NO') -> Element:
    elem = Element('route', {
        'src': src_id, 'dst': dst_id, 'symmetrical': symmetrical})
    for link_id in link_ids:
        elem.append(Element('link_ctn', {'id': link_id}))
    return elem


def link_elem(link_id: str, bandwidth: str, latency: str) -> Element:
    elem = Element('link',
            { 'id': link_id,
              'bandwidth': bandwidth,
              'latency': latency})
    return elem


def is_disk(member: Element) -> bool:
    props = member.findall("prop")
    return any(['value' in prop.attrib and prop.attrib['value'] == 'storage'
        for prop in props])


def do_add_host(new_zone, index, new_host_id, speed, core,
        up_bw, down_bw, latency):
    new_zone.insert(index, host_elem(new_host_id, speed, core))
    index = index + 1

    # adding one link for read and one for write
    link_up = new_host_id + "_UP"
    link_down = new_host_id + "_DOWN"
    link_local = new_host_id + "_loopback"
    new_zone.insert(index,
            link_elem(link_up, up_bw, latency))
    index = index + 1
    new_zone.insert(index,
            link_elem(link_down, down_bw, latency))
    index = index + 1
    new_zone.insert(index,
            link_elem(link_local, "6E9Bps", "1.0E-9s"))
    index = index + 1


def add_host(root: Element, up_bw: str, down_bw: str,
        latency: str, speed: str, core: int, new_host_id: str):
    for zone_index, zone in enumerate(root):
        if zone.tag != "zone" and zone.tag != "AS":
            continue
        new_zone = Element("zone", zone.attrib)
        index = 0
        hosts: List[str] = []
        links: List[Element] = []
        host_added = False

        # Bootrap with the first node if no hosts already present
        if len(zone) == 0:
            do_add_host(new_zone, index, new_host_id, speed, core, up_bw, down_bw, latency)
        else:
            for member in zone:
                # Get first last host
                new_zone.append(member)
                # Get the first host to put the host in his place
                if member.tag == 'host' and not host_added:
                    # Now add the host
                    do_add_host(new_zone, index, new_host_id, speed, core, up_bw, down_bw, latency)
                    host_added = True

                if member.tag == 'host' and not is_disk(member):
                    # register host ids to add routes to them later
                    hosts.append(member.attrib['id'])

                if member.tag == 'link' and len(hosts) > 0:
                    links.append(member)

        # add loopback
        new_zone.append(route_elem(new_host_id, new_host_id,
                [new_host_id + "_loopback"], symmetrical='YES'))

        # add routes from node to disk at the end of the zone
        for host_id in hosts:
            if (not any([host_id + "_UP" == link.attrib["id"] for link in links])) or (not any( [host_id + "_DOWN" == link.attrib["id"] for link in links])):
                raise Exception(
                   "WARNING: Assuming that each host has an '_UP' link that will be used "
                   "for PFS write and a '_DOWN' link used for PFS read.")

            link_up = new_host_id + "_UP"
            link_down = new_host_id + "_DOWN"
            new_zone.append(route_elem(new_host_id, host_id,
                [link_up, host_id + "_DOWN"]))
            new_zone.append(route_elem(host_id, new_host_id,
                [host_id + "_UP", link_down]))

        # replace existing zone with the new one
        root[zone_index] = new_zone



def add_pfs(root: Element, read_bw: str, write_bw: str,
        disk_access_latency: str, pfs_id: str="pfs"):
    for zone_index, zone in enumerate(root):
        if zone.tag != "zone" and zone.tag != "AS":
            continue
        new_zone = Element("zone", zone.attrib)
        index = 0
        hosts: List[str] = []
        links: List[Element] = []
        pfs_added = False
        for member in zone:
            # Get first last host
            new_zone.append(member)
            # Get the first host to put the pfs in his place
            if member.tag == 'host' and not pfs_added:
                # Now add the pfs
                new_zone.insert(index, disk_elem(pfs_id))
                index = index + 1

                # adding one link for read and one for write
                link_read = pfs_id + "_IO_read"
                link_write = pfs_id + "_IO_write"
                new_zone.insert(index,
                        link_elem(link_read, read_bw, disk_access_latency))
                index = index + 1
                new_zone.insert(index,
                        link_elem(link_write, write_bw, disk_access_latency))
                index = index + 1
                pfs_added = True

            if member.tag == 'host' and not is_disk(member):
                # register host ids to add routes to them later
                hosts.append(member.attrib['id'])

            if member.tag == 'link' and len(hosts) > 0:
                links.append(member)

        # add routes from node to disk at the end of the zone
        for host_id in hosts:
            if (not any([host_id + "_UP" == link.attrib["id"] for link in links])) or (not any( [host_id + "_DOWN" == link.attrib["id"] for link in links])):
                raise Exception(
                   "WARNING: Assuming that each host has an '_UP' link that will be used "
                   "for PFS write and a '_DOWN' link used for PFS read.")
            new_zone.append(route_elem(pfs_id, host_id,
                [link_write, host_id + "_DOWN"]))
            new_zone.append(route_elem(host_id, pfs_id,
                [host_id + "_UP", link_read]))

        # replace existing zone with the new one
        root[zone_index] = new_zone


def add_dfs(root, read_bw, write_bw, disk_access_latency):
    for zone_index, zone in enumerate(root):
        if zone.tag != "zone" and zone.tag != "AS":
            continue
        new_zone = Element("zone", zone.attrib)
        index = 0
        route_list = []
        for member in zone:
            # Adding disk to hosts
            new_zone.append(member)
            index = index + 1
            # print(member.tag + ": " + str(member.attrib))
            if member.tag == 'host' and not is_disk(member):
                elem_id = member.attrib['id']
                disk_id = elem_id + "_disk"
                new_zone.insert(index, disk_elem(disk_id))
                index = index + 1

                # adding one link for read and one for write
                link_read = elem_id + "_IO_read"
                link_write = elem_id + "_IO_write"
                new_zone.insert(index,
                        link_elem(link_read, read_bw, disk_access_latency))
                index = index + 1
                new_zone.insert(index,
                        link_elem(link_write, write_bw, disk_access_latency))
                index = index + 1
                # Create routes for later
                route_list.append(route_elem(disk_id, elem_id, [link_read]))
                route_list.append(route_elem(elem_id, disk_id, [link_write]))

        # add routes from node to disk at the end of the zone
        for route in route_list:
            new_zone.append(route)
        root[zone_index] = new_zone


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
            description=__doc__)
    parser.add_argument('input_platform', type=argparse.FileType('r'),
            help="A simgrid XML platfom")
    parser.add_argument('variant', type=str, choices=["DFS", "PFS"],
            help='File system variant: "PFS" or "DFS"')
    parser.add_argument('-o', '--output_platform', type=argparse.FileType('wb'),
            default="output.xml",
            help="The modified simgrid XML platfom")
    parser.add_argument('--storage_read_bw', type=str, default="150MBps",
            help='The bandwidth to read from disk. '
            'Format is the simgrid link bandwith property format')
    parser.add_argument('--storage_write_bw', type=str, default="80MBps",
            help='The bandwidth to write to disk'
            'Format is the simgrid link bandwith property format')
    parser.add_argument('--storage_latency', type=str, default="4ms",
            help='The disk access latency'
            'Format is the simgrid link bandwith property format')
    args = parser.parse_args()

    storage_read_bw = args.storage_read_bw
    storage_write_bw = args.storage_write_bw
    disk_access_latency = args.storage_latency
    tree = ElementTree()
    root = tree.parse(args.input_platform)

    if args.variant == "PFS":
        add_pfs(root, storage_read_bw, storage_write_bw, disk_access_latency)
    elif args.variant == "DFS":
        add_dfs(root, storage_read_bw, storage_write_bw, disk_access_latency)
    else:
        raise Exception("This should not happen!")

    header = '''<?xml version='1.0'?>
<!DOCTYPE platform SYSTEM "http://simgrid.gforge.inria.fr/simgrid/simgrid.dtd">'''
    with args.output_platform as f:
        f.write(header.encode('utf8'))
        tree.write(f, 'utf-8', xml_declaration=False)
    print("Modified platform is available here:\n{}".format(
        args.output_platform.name))
