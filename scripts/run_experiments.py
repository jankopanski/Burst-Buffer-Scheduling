#!/usr/bin/env python3
# ./scripts/run_experiments.py
import os
import sys
import json
from collections import namedtuple
from subprocess import Popen

from batsim.cmds.launcher import main


Params = namedtuple('Params', ['prefix', 'scheduler', 'depth'])

batsim_template_cmd = (
    './run_batsim_docker.sh '
    '-p platforms/dragonfly96.xml '
    '-w workloads/{workload} '
    '-r node_0,node_9,node_18,node_27,node_36,node_45,'
    'node_54,node_63,node_72,node_81,node_90,node_99:storage '
    '-e output/{output_dir}/{prefix}'
)

####################################################################################################
output_dir = 'KTH-1000-workloads-std'

workloads = [
    'KTH-SP2-1996-2.1-cln-std-1000-1.json',
    'KTH-SP2-1996-2.1-cln-std-1000-2.json',
    'KTH-SP2-1996-2.1-cln-std-1000-3.json',
    'KTH-SP2-1996-2.1-cln-std-1000-4.json',
    'KTH-SP2-1996-2.1-cln-std-1000-5.json',
]

policies = [
    Params('fcfs', 'fcfsAllocOnlyScheduler.py', None),
    Params('filler', 'fillerAllocOnlyScheduler.py', None),
    Params('backfill-1', 'backfillAllocOnlyScheduler.py', 1),
    Params('backfill-1', 'backfillAllocOnlyScheduler.py', 1),
    Params('backfill-2', 'backfillAllocOnlyScheduler.py', 2),
    Params('backfill-3', 'backfillAllocOnlyScheduler.py', 3),
    Params('backfill-4', 'backfillAllocOnlyScheduler.py', 4),
    Params('backfill-5', 'backfillAllocOnlyScheduler.py', 5),
    Params('backfill-6', 'backfillAllocOnlyScheduler.py', 6),
    Params('backfill-7', 'backfillAllocOnlyScheduler.py', 7),
    Params('backfill-8', 'backfillAllocOnlyScheduler.py', 8),
]
####################################################################################################

if os.path.basename(os.getcwd()) == 'scripts':
    os.chdir('..')
os.makedirs(os.path.join('output', output_dir), exist_ok=True)

for i, workload in enumerate(workloads, 1):
    for policy in policies:
        files_prefix = 'workload-{}_{}'.format(i, policy.prefix)
        batsim_cmd = batsim_template_cmd.format(
            workload=workload, output_dir=output_dir, prefix=files_prefix)

        with Popen(batsim_cmd.split()):
            scheduler_options = {
                'platform': 'platforms/dragonfly96.yaml',
                'progress_bar': True,
                'allow_schedule_without_burst_buffer': False,
                'backfilling_reservation_depth': policy.depth
            }
            sys.argv = [
                sys.argv[0],
                '-v', 'warn',
                os.path.join('burstbuffer', policy.scheduler),
                '-o', json.dumps(scheduler_options)
            ]
            main()
