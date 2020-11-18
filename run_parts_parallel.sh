#!/usr/bin/env bash

# ./run_parts.sh io fcfs

MODEL=$1  # io/alloc
CONFIG=$2  # scheduler options file

PARTS=16
FIRST_PORT=28005

source sim/bin/activate

for (( i=0; i<$PARTS; i++ )); do
  export BATSIM_PORT=$((FIRST_PORT+i))
  echo $BATSIM_PORT
  echo ${CONFIG}_part-$i
  if [ $MODEL == "io" ]; then
    ./run_batsim_docker.sh -w workloads/KTH-split/io-aware/part-$i.json -e output/KTH-split/io-aware/${CONFIG}_part-$i --enable-dynamic-jobs --enable-profile-reuse &
    pids[${i}]=$!
    python -O pybatsim/launcher.py -v warn -t 60000 burstbuffer/schedIOAware.py -O configs/$CONFIG.json -s tcp://127.0.0.1:$BATSIM_PORT &
    pids[${i}]=$!
  else
    ./run_batsim_docker.sh -w workloads/KTH-split/alloc-only/part-$i.json -e output/KTH-split/alloc-only/${CONFIG}_part-$i  &
    pids[${i}]=$!
    python -O pybatsim/launcher.py -v warn -t 60000 burstbuffer/schedAllocOnly.py -O configs/$CONFIG.json -s tcp://127.0.0.1:$BATSIM_PORT &
    pids[${i}]=$!
  fi
  sleep 1  # For the BATSIM_PORT export
done

# wait for all pids
for pid in ${pids[*]}; do
    wait $pid
done
