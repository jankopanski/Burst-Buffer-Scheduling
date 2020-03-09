#!/usr/bin/env python3
import add_disks
from xml.etree.ElementTree import ElementTree, Element
from typing import List

tree = ElementTree()
root = tree.parse("./platform_graphene_s1.xml")
for i in range(17, 34):
    add_disks.add_host(root, '1.25E8Bps', '1.25E8Bps', "1.0E-4s", "16.673E9f",
            4, "graphene-"+str(i)+".nancy.grid5000.fr")

header = '''<?xml version='1.0'?>
<!DOCTYPE platform SYSTEM "http://simgrid.gforge.inria.fr/simgrid/simgrid.dtd">'''
with open("./platform_graphene_s1_full.xml", 'wb') as f:
    f.write(header.encode('utf8'))
    tree.write(f, 'utf-8', xml_declaration=False)
