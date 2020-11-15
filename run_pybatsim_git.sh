#!/usr/bin/env bash

# Run with arguments defined inside the script
#./run_pybatsim_git.sh burstbuffer/schedAllocOnly.py platforms/dragonfly.yaml
#scheduler_config="{\"platform\": \"$2\", \"progress_bar\": false}"
#echo "$scheduler_config"
#python pybatsim/launcher.py -v warn "$1" -o "$scheduler_config" 2> /dev/null

# AllocOnlyScheduler
#./run_pybatsim_git.sh burstbuffer/schedAllocOnly.py scheduler_options.json

# IOAwareScheduler
#./run_pybatsim_git.sh burstbuffer/schedIOAware.py scheduler_options.json

[ -z "$(ls -A pybatsim/)" ] && git submodule update --init

source sim/bin/activate

set -x

python -O pybatsim/launcher.py -v warn -t 10000 "$1" -O "$2"
