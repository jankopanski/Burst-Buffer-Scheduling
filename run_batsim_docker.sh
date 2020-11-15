#!/usr/bin/env bash

# AllocOnlyScheduler
#./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-alloc-only.json -e output/out

# IOAwareScheduler
#./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-io-aware.json -e output/out --enable-dynamic-jobs --enable-profile-reuse

[ -z "$BATSIM_PORT" ] && BATSIM_PORT=28000

user_id=$(id -u)
group_id=$(id -g)
if [[ "$OSTYPE" == "linux-gnu" ]]; then
  set -x; docker run --rm \
    --net host \
    -u $user_id:$group_id \
    -v $PWD:/data \
    -m 9G \
    oarteam/batsim:4.0.0 \
    -s tcp://127.0.0.1:$BATSIM_PORT \
    -p platforms/dragonfly96.xml \
    -r node_0,node_9,node_18,node_27,node_36,node_45,node_54,node_63,node_72,node_81,node_90,node_99:storage \
    -q \
    "$@"
elif [[ "$OSTYPE" == "darwin"* ]]; then
  set -x; docker run --rm \
    --net host \
    -u $user_id:$group_id \
    -v $PWD:/data \
    oarteam/batsim:4.0.0 \
    -s tcp://host.docker.internal:$BATSIM_PORT \
    -p platforms/dragonfly96.xml \
    -r node_0,node_9,node_18,node_27,node_36,node_45,node_54,node_63,node_72,node_81,node_90,node_99:storage \
    -q \
    "$@"
else
  echo "OS not supported"
  exit 1
fi
