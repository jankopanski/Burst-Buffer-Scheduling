#!/usr/bin/env python3
# python ./scripts/swf_checker.py ../swf

import os
from sys import argv
from joblib import Parallel, delayed

from burstbuffer.swf import SWFJob


def process_swf(swf_filename):
    used_memory = []
    requested_memory = []
    requested_nodes = []
    swf_path = os.path.join(input_swf_dir, swf_filename)
    swf = open(swf_path)
    for line in swf:
        job = SWFJob.parse_line(line)
        if not job:
            continue

        used_memory.append(job.used_memory >= 0)
        requested_memory.append(job.requested_memory >= 0)
        requested_nodes.append(job.requested_processors >= 0)

    print(
        swf_filename,
        'OR', any(used_memory), any(requested_memory), any(requested_nodes),
        'AND', all(used_memory), all(requested_memory), all(requested_nodes),
        'SUM', sum(used_memory), sum(requested_memory), sum(requested_nodes),
        'ALL', len(requested_nodes)
    )


input_swf_dir = argv[1]
Parallel(n_jobs=8)(delayed(process_swf)(swf_filename) for swf_filename in os.listdir(input_swf_dir))
# for swf_filename in os.listdir(input_swf_dir):
#     process_swf(swf_filename)
