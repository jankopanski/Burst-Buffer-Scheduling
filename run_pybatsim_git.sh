#!/usr/bin/env bash
[ ! -d "pybatsim" ] && git clone https://gitlab.inria.fr/batsim/pybatsim.git
# ./run_pybatsim_git.sh schedulers/fcfsAllocOnlyScheduler.py platforms/dragonfly.yaml
#scheduler_config="{\"platform\": \"$2\", \"progress_bar\": false}"
#echo "$scheduler_config"
#python pybatsim/launcher.py -v warn "$1" -o "$scheduler_config" 2> /dev/null
#
# ./run_pybatsim_git.sh schedulers/fcfsAllocOnlyScheduler.py scheduler_options.json
python pybatsim/launcher.py -v warn "$1" -O "$2"
