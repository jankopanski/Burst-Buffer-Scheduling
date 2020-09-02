#!/usr/bin/env bash
# ./run_batsim_docker.sh platforms/two_nodes_bb_pfs.xml workloads/example_compute_with_bb.json

# ./run_batsim_docker.sh --enable-dynamic-jobs -p platforms/two_nodes_bb_pfs.xml
# -w workloads/example_compute_with_bb.json

# ./run_batsim_docker.sh -p platforms/dragonfly.xml -w workloads/generated_cluster30_jobs100.json
# -r node_0,node_6,node_12,node_18,node_24,node_30:storage

#./run_batsim_docker.sh -p platforms/dragonfly96.xml -w workloads/KTH-SP2-1996-2.1-cln-1000-1.json
#-r node_0,node_9,node_18,node_27,node_36,node_45,node_54,node_63,node_72,node_81,node_90,node_99:storage -e output/out

#platform=$1
#workload=$2

user_id=$(id -u)
group_id=$(id -g)
if [[ "$OSTYPE" == "linux-gnu" ]]; then
  set -x; docker run --rm \
    --net host \
    -u $user_id:$group_id \
    -v $PWD:/data \
    oarteam/batsim:4.0.0 \
    -q \
    "$@"
elif [[ "$OSTYPE" == "darwin"* ]]; then
  set -x; docker run --rm \
    --net host \
    -u $user_id:$group_id \
    -v $PWD:/data \
    oarteam/batsim:4.0.0 \
    -s tcp://host.docker.internal:28000 \
    -q \
    "$@"
else
  echo "OS not supported"
  exit 1
fi
