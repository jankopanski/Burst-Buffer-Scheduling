#!/usr/bin/env bash
# ./run_batsim_docker.sh platforms/two_nodes_bb_pfs.xml workloads/example_compute_with_bb.json

# ./run_batsim_docker.sh --enable-dynamic-jobs -p platforms/two_nodes_bb_pfs.xml
# -w workloads/example_compute_with_bb.json

# ./run_batsim_docker.sh -p platforms/dragonfly.xml -w workloads/generated_cluster30_jobs100.json
# -r node_0,node_6,node_12,node_18,node_24,node_30:storage

#platform=$1
#workload=$2

user_id=$(id -u)
group_id=$(id -g)
if [[ "$OSTYPE" == "linux-gnu" ]]; then
  set -x; docker run --rm \
    --net host \
    -u $user_id:$group_id \
    -v $PWD:/data \
    oarteam/batsim:3.1.0 \
    -q -e output/out \
    "$@"
elif [[ "$OSTYPE" == "darwin"* ]]; then
  set -x; docker run --rm \
    --net host \
    -u $user_id:$group_id \
    -v $PWD:/data \
    oarteam/batsim:3.1.0 \
    -s tcp://host.docker.internal:28000 \
    -q -e output/out \
    "$@"
else
  echo "OS not supported"
  exit 1
fi
