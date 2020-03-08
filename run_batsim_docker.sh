#!/usr/bin/env bash
# ./run_batsim_docker.sh platforms/two_nodes_bb_pfs.xml workloads/example_compute_with_bb.json

platform=$1
workload=$2

if [[ "$OSTYPE" == "linux-gnu" ]]; then
  set -x; docker run --rm \
    --net host \
    -u $(id -u):$(id -g) \
    -v $PWD:/data \
    oarteam/batsim:3.1.0 \
    --enable-dynamic-jobs -q \
    -e output/out \
    -p $platform -w $workload
elif [[ "$OSTYPE" == "darwin"* ]]; then
  set -x; docker run --rm \
    --net host \
    -u $(id -u):$(id -g) \
    -v $PWD:/data \
    oarteam/batsim:3.1.0 \
    -s tcp://host.docker.internal:28000 \
    --enable-dynamic-jobs -q \
    -e output/out \
    -p $platform -w $workload
else
  echo "OS not supported"
  exit 1
fi
