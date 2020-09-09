#!/usr/bin/env bash
[ ! -d "pybatsim" ] && git submodule update --init

set -x

# ./run_pybatsim_git.sh burstbuffer/fcfsAllocOnlyScheduler.py platforms/dragonfly.yaml
#scheduler_config="{\"platform\": \"$2\", \"progress_bar\": false}"
#echo "$scheduler_config"
#python pybatsim/launcher.py -v warn "$1" -o "$scheduler_config" 2> /dev/null

# ./run_pybatsim_git.sh burstbuffer/fcfsAllocOnlyScheduler.py scheduler_options.json
python pybatsim/launcher.py -v warn "$1" -O "$2"
