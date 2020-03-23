#!/usr/bin/env bash
# ./run_pybatsim_git.sh schedulers/burstBufferScheduler.py
[ ! -d "pybatsim" ] && git clone https://gitlab.inria.fr/batsim/pybatsim.git
python pybatsim/launcher.py -v warn "$1"