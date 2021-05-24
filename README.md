# Plan-based Job Scheduling for Supercomputers with Shared Burst Buffers
## Getting Started Guide
Software requirements:
 - Linux or macOS
 - Bash
 - Git
 - Virtualenv
 - Docker

### Introduction
This publication is dedicated to job scheduling for supercomputers. All experiments were conducted in a simulated environment. The simulation consists of several components, which are illustrated below:
 - Batsim simulator
 https://batsim.readthedocs.io/en/latest/
 https://gitlab.inria.fr/batsim/batsim
 - Pybatsim scheduler
 https://gitlab.inria.fr/batsim/pybatsim
 - Simulated platform definition
 - Input workload

![Batsim architecture](https://raw.githubusercontent.com/jankopanski/Burst-Buffer-Scheduling/master/images/Batsim-architecture.png)

Batsim is a simulator framework of Resources and Jobs Management Systems. In other words, Batsim is a dedicated simulator for analysis of batch schedulers. 
In terms of software execution, the Batsim simulation consists in two processes created in an operating system:
 - Supercomputer simulator process (Batsim simulator)
 - Job scheduler processs (Pybatsim scheduler)

These two processes communicate using a socket with a custom Batsim network protocol. More information on the network protocol can be found here: https://batsim.readthedocs.io/en/latest/protocol.html.

### Code repository
**Step 1.** Start with cloning the code reportitory.
```bash
git clone https://github.com/jankopanski/Burst-Buffer-Scheduling.git
cd Burst-Buffer-Scheduling
```
**Please note** that for the rest of this guide all shell commands should be executed from the repository root directory (Burst-Buffer-Scheduling)

This repository contains two git submodules:
 - pybatsim
Required. Our fork of Pybatsim, which has several minor bug fixes. Note that our code will not work the official Pybatsim.
https://github.com/jankopanski/pybatsim
 - thesis
Optional. Jan Kopanski's master thesis. It may be used as complementary study to the publication, as well as, this guide. It includes detail describtions of software components (Batsim, SimGrid) and configuration files (platform, workload).
https://github.com/jankopanski/Masters-Thesis

**Step 2.** Initialise pybatsim submodule.
```bash
git submodule update --init pybatsim
```
This step is in fact optional as it would be automatically performed by `run_pybatsim_git.sh` script.

### Python
Virtualenv can be installed using pip (https://pypi.org/project/virtualenv/):
```bash
pip install virtualenv
```

We need to create two Python environments:
 - tools - for workload generation and results analysis
CPython, Python 3.8
Creating this one is optional, because the generated workloads are already available in the repository.
 - sim - for experiments
PyPy, Python 3.7

**Step 3.** Create `tools` environment
We need a Python 3.8, because `scripts/generate_swf_workload.py` uses syntax introduced in 3.8.
You may create this Python environment using `setup_tools_env.py` script.
```bash
./setup_tools_env.sh
```
The content of this scrip is following:
```bash
#!/usr/bin/env bash

set -e  # Terminate script on error
set -x  # Print commands

virtualenv -p python3.8 tools
source tools/bin/activate
pip install --upgrade pip
pip install --upgrade setuptools
pip install -r tools-requirements.txt
```
You may notice in `tools-requirements.txt` that we are using an old version of pandas (0.25.3), which is because of a dependency from evalys --- library for visualisation of Batsim traces.

**Step 4.** Create `sim` environment
Our experiments can take significat time and are bounded by Python execution time. To speed up simulations, we used PyPy implementation of Python as oppose to default CPython. This brings about 2.5x speedup.
```bash
./setup_simulator_env.sh
```
Script content:
```bash
#!/usr/bin/env bash

set -e  # Terminate script on error
set -x  # Print commands

wget https://downloads.python.org/pypy/pypy3.7-v7.3.2-linux64.tar.bz2
tar xf pypy3.7-v7.3.2-linux64.tar.bz2
virtualenv -p pypy3.7-v7.3.2-linux64/bin/pypy sim
source sim/bin/activate
pip install --upgrade pip
pip install --upgrade setuptools
pip install -r simulator-requirements.txt
```

### Batsim installation
Batsim developers recommend installing it using Nix. We prefer to use the Batsim simulator from inside of a Docker container, because we find it easier to set it up on macOS and remote clusters. It should be also possible to run Batsim using Singularity on HPC clusters that don't support native Docker. However, we didn't test this workflow, so it might require some additional steps.

To install Docker, you may follow the instructions at https://www.docker.com/.

**Step 5.** Download Batsim docker image
```bash
docker pull oarteam/batsim:4.0.0
```
This step would be also automatically performed when running `run_batsim_docker.sh` for the first time. More information on Batsim installation is available here: https://batsim.readthedocs.io/en/latest/installation.html#using-batsim-from-a-docker-container.

Now you have all necessary software to generate workloads, run simulations and analyse results.

## Step-by-Step Instructions

### Workload generation
Our experimental workload is based on the KTH-SP2-1996-2.1-cln workload from the [Parallel Workloads Archive](https://www.cs.huji.ac.il/labs/parallel/workload/). The original workload is given in the Standard Workload Format (SWF). Furthermore, it does not contain information on the requested burst buffers. We converted the KTH-SP2-1996-2.1-cln workload to the [Batsim format](https://batsim.readthedocs.io/en/latest/input-workload.html) (JSON) and supplemented it with a burst buffer requests generated from a modelled distribution. We extended the Batsim job profile format with an additional field `bb` describing requested burst buffer size per node in bytes.

The KTH-SP2-1996-2.1-cln workload can be downloaded here:
https://www.cs.huji.ac.il/labs/parallel/workload/l_kth_sp2/index.html
However, we also keep a copy of this workload in `workloads/swf/KTH-SP2-1996-2.1-cln.swf`.

The converted workload used in the experiments presented in the paper is available in our code repository in the file `workloads/KTH-SP2-1996-2.1-cln-io-aware.json`.

There is also a shorter version available that consists of the first 1000 jobs from the original SWF workload: `workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json`

You may also notice a file `workloads/KTH-SP2-1996-2.1-cln-alloc-only.json`. In fact, we created two simulation models:

 1. Alloc-Only - simulates only resource allocation for job with execution of computations and MPI-like communication.
 2. IO-Aware - extends Alloc-Only model with I/O traffic simulation (stage-in, stage-out, checkpointing)

In the paper, only the results for the IO-Aware model are presented due to the limited space in the Euro-Par paper format. Detailed describtion of differences between IO-Aware and Alloc-Only models can be found in the thesis in Section 2.4.

Lastly, the split workloads used to create Figures 11 and 12 in the paper are available in `workloads/KTH-split/io-aware/`.

Below, we present how to reproduce the workloads.

**Step 6.** Generate the full workload
```bash
source setup_path.sh
source tools/bin/activate
./scripts/generate_swf_workload.py platforms/dragonfly96.yaml workloads/swf.yaml \
workloads/swf/KTH-SP2-1996-2.1-cln.swf workloads/my-KTH-SP2-1996-2.1-cln-io-aware.json
```

 - `platforms/dragonfly96.yaml` - simulated platform configuration
 - `workloads/swf.yaml` - options for generated workload
 - `workloads/swf/KTH-SP2-1996-2.1-cln.swf` - input SWF workload
 - `workloads/my-KTH-SP2-1996-2.1-cln-io-aware.json` - output Batsim workload

The generated workload may differ from `workloads/KTH-SP2-1996-2.1-cln-io-aware.json` because of a random seed.

**Step 7.** Generate the truncated workload
```bash
cp workloads/swf.yaml workloads/my-swf.yaml
```
Open `my-swf.yaml` and in the first line change the `num_jobs` option from `null` to `1000`. Also change `from_job_number` option from `0` to `15` (the original workload starts with job 15). Your `my-swf.yaml` configuration should look as follows:
```yaml
num_jobs: 1000  # Limit for the number of jobs to generate (null for no limit)
from_job_number: 15  # Job number in swf file from which generating starts 
# (0 to start from the beginning)
time_distribution_lambda: 0
time_distribution_k: 0
expected_log_num_nodes: 0
stddev_log_num_nodes: 0
expected_computations_per_node: 0  # GFLOPS
stddev_computations_per_node: 0  # %
lambda_scale_computations_per_node: 0
multiply_factor_computations_per_node: 0  # GFLOPS
expected_communication_per_node: 0.1  # GB
stddev_communication_per_node: 0.2  # %
expected_burst_buffer_per_node: 0  # GB
stddev_burst_buffer_per_node: 0  # %
multiply_factor_walltime: 0
stddev_walltime: 0  # not a %
multiply_factor_runtime: 40
```
The fields `expected_communication_per_node` and `stddev_communication_per_node` generate requirements for MPI-like communication from a gaussian distribution. `multiply_factor_runtime` is resposible for shortening computation phases of jobs to make space for new I/O phases without walltime modification. The rest of the fields were used only in `scripts/generate_probabilistic_workload.py`, which generates an artificial workload.

There is no need to `source setup_path.sh` and `tools/bin/activate` if you have already done it in the previous step. 
```bash
source setup_path.sh
source tools/bin/activate
./scripts/generate_swf_workload.py platforms/dragonfly96.yaml workloads/my-swf.yaml \
workloads/swf/KTH-SP2-1996-2.1-cln.swf workloads/my-KTH-SP2-1996-2.1-cln-io-aware-1000.json
```

### Running experiments
For running experiments you need to have two terminal windows opened.

For simulating the full workload, a machine with at least 16 GB of RAM is required. Particularly, the simulator process requires at least 9 GB. If using macOS, you might need to set maximum memory in Docker Desktop. For the truncated workload on maxOS, you may instead want to modify the run command in `run_batsim_docker.sh` script. Simply set `-m 9G` flag to a lower value. Please note that setting the available memory to too low value will result with a termination of the Batsim simulator process without any meaningful error message.

Simulating the full workload can take up to 4 days depending on the specified configuration and scheduling algorithm. Therefore, we show how to run experiments with the truncated workload, which should take a few minutes per experiment.

**Step 8.** Run simulator process
```bash
./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json -e output/out \
--enable-dynamic-jobs --enable-profile-reuse
```

 - `-w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json` - the workload file
 - `-e output/out` - output path; `output` is the directory name and `out` is the prefix of generated files.
 - `--enable-dynamic-jobs --enable-profile-reuse` flags are required for the IO-Aware model. Do not use them for the Alloc-Only model.

The simulator process will now wait for starting of the scheduler process. You should see a following output.
```
+ docker run --rm --net host -u 1012:1013 
-v /home/jkopanski/artifact/Burst-Buffer-Scheduling:/data 
-m 9G oarteam/batsim:4.0.0 -s tcp://127.0.0.1:28000 -p platforms/dragonfly96.xml 
-r node_0,node_9,node_18,node_27,node_36,node_45,node_54,node_63,node_72,node_81,node_90,
node_99:storage 
-q -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json -e output/out 
--enable-dynamic-jobs --enable-profile-reuse
[0.000000] [batsim/INFO] Workload 'w0' corresponds to workload file
'/data/workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json'.
[0.000000] [batsim/INFO] Batsim version: 4.0.0
[0.000000] [xbt_cfg/INFO] Configuration change: Set 'host/model' to 'ptask_L07'
[0.000000] [batsim/INFO] Checking whether SMPI is used or not...
[0.000000] [xbt_cfg/INFO] Switching to the L07 model to handle parallel tasks.
[0.000000] [batsim/INFO] Batsim's export prefix is 'output/out'.
[0.000000] [batsim/INFO] The process 'workload_submitter_w0' has been created.
[0.000000] [batsim/INFO] The process 'server' has been created.
```
Please note that we are using port 28000 for inter-process communication, so it should not be taken by other applications.

**Step 9.** Run scheduler process
Scheduler is written entirely in Python and it is mostly a single threaded program.
In the **second terminal window** run the following command:
```
./run_pybatsim_git.sh burstbuffer/schedIOAware.py scheduler_options.json
```
The script will automatically activate `sim` environment. You should see output similar to this one:
```
+ python -O pybatsim/launcher.py -v warn -t 10000 burstbuffer/schedIOAware.py 
-O scheduler_options.json
[pybatsim - 2021-05-14 01:53:24,349 - SchedIOAware_Events - INFO]
"time";"level";"processed_jobs";"open_jobs";"type";"message";"data"
Scheduler: BaseBatsimScheduler ({'platform': 'platforms/dragonfly96.yaml',
'progress_bar': True, 'debug': False, 'algorithm': 'backfill',
'allow_schedule_without_burst_buffer': False, 'future_burst_buffer_reservation': True, 
'backfilling_reservation_depth': 1, 'priority_policy': 'sjf', 'optimisation': False, 
'balance_factor': 1, 'compute_threshold': 2, 'storage_threshold': 2, 'window_size': 10, 
'max_num_compute_phases': 10, 'target_compute_phase_size': 3600})
[pybatsim - 2021-05-14 01:53:24,509 - batsim.batsim - WARNING] Dynamic registration of jobs 
is ENABLED. The scheduler must send a NOTIFY event of type 'registration_finished' to let 
Batsim end the simulation.
100%|###################################################| 1000/1000 [01:10<00:00, 14.14it/s]
# Rejected jobs: Too few resources available in the system (overall):  0
# Rejected jobs: Too much requested burst buffer space for a single node:  0
# Rejected jobs: Too much total requested burst buffer space:  0
# filler job schedulings with insufficient compute resources: 16389
# filler job schedulings with insufficient burst buffers: 8188
# backfill job schedulings with insufficient burst buffers: 0
Simulation ran for: 0:01:10.919103
Job submitted: 40614 , scheduled: 39614 , rejected: 1000 , killed: 0 , changed: 0 , 
timeout: 8 , success 39606 , complete: 39614
```
In the `output` directory there should be four new files: out_jobs.csv, out_machine_states.csv, out_schedule.csv, out_schedule.trace. 

The first argument of this script is the scheduler file, which specifies a simulation model. Available options are: `burstbuffer/schedIOAware.py` and `burstbuffer/schedAllocOnly.py`.
The second argument is a path to a configuration file for the scheduler. By default, SJF-Backfilling with future burst buffer reservations will be used as the scheduling algorithm (*sjf-bb* in the paper). 
The content of `scheduler_options.json` is following:
```json
{
  "platform": "platforms/dragonfly96.yaml",
  "progress_bar": true,
  "debug": false,
  "algorithm": "backfill",
  "allow_schedule_without_burst_buffer": false,
  "future_burst_buffer_reservation": true,
  "backfilling_reservation_depth": 1,
  "priority_policy": "sjf",
  "optimisation": false,
  "balance_factor": 1,
  "compute_threshold": 2,
  "storage_threshold": 2,
  "window_size": 10,
  "max_num_compute_phases": 10,
  "target_compute_phase_size": 3600
}
```
Here we describe possible options in the `scheduler_options.json` file:
 1. platform - path to yaml plaform configuration.
 2. progress_bar (true/false) - turns on/off tqdm progress bar.
 3. debug (true/false) - turns on/off logging in pybatsim. When debug is true, set the progress_bar to false.
 4. algorithm ("fcfs", "filler", "backfill", "plan", "maxutil", "window") - *maxutil* and *window* scheduling policies were not presented in the paper.
 5. allow_schedule_without_burst_buffer (true/false) - allows to ignore burst buffer requests.
 6. future_burst_buffer_reservation (true/false) - *fcfs-easy* from the paper is the backfill algorithm with future_burst_buffer_reservation set to false; *fcfs-bb* and *sjf-bb* are backfill with future_burst_buffer_reservation set to true.
 7. backfilling_reservation_depth (integer >= 0) - specifies how many jobs should receive resource reservations prior to backfilling. When set to 1, then it is a standard EASY-backfilling (aggresive backfilling).
 8. priority_policy (null, "sjf", "sum", "square", "cube") - null results in FCFS policy; for *plan* algorithm sum, square, cube stand for the value 1, 2, 3 of the parameter $\alpha$ consecutively.
 9. optimisation (true/false) - set to true when running *plan* scheduling.
 10. balance_factor (float > 0) - only relevant to maxutil and window algorithms.
 11. compute_threshold - deprecated.
 12. storage_threshold - deprecated.
 13. window_size - maximum number of jobs for optimisation in the window algorithm.
 14. max_num_compute_phases (integer >= 1) - maximum number of compute phases interleaved with I/O phases.
 15. target_compute_phase_size - deprecated.

### Reproducing experiments
Here we summarise shell commands and `scheduler_options.json` settings used to run experiments presented in Figures 5-10 in the paper. For `scheduler_options.json` file we only show options that are required to modify.
To keep runtime of simulations short, we present the commands for the truncated workload. To reproduce full experiments, use `workloads/KTH-SP2-1996-2.1-cln-io-aware.json` workload file instead. Please note that simulations are deterministic.

In all cases, the same command for running scheduler should be used:
```bash
./run_pybatsim_git.sh burstbuffer/schedIOAware.py scheduler_options.json
```
**Step 10.** Perform the following experiments
1. *filler*
```json
  "algorithm": "filler",
  "future_burst_buffer_reservation": false,
  "priority_policy": null,
  "optimisation": false,
```
```bash
./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json \
-e output/filler --enable-dynamic-jobs --enable-profile-reuse
```
2. *fcfs*
```json
  "algorithm": "fcfs",
  "future_burst_buffer_reservation": false,
  "priority_policy": null,
  "optimisation": false,
```
```bash
./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json \
-e output/fcfs --enable-dynamic-jobs --enable-profile-reuse
```
3. *fcfs-easy*
```json
  "algorithm": "backfill",
  "future_burst_buffer_reservation": false,
  "priority_policy": null,
  "optimisation": false,
```
```bash
./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json \
-e output/fcfs-easy --enable-dynamic-jobs --enable-profile-reuse
```
4. *fcfs-bb*
```json
  "algorithm": "backfill",
  "future_burst_buffer_reservation": true,
  "priority_policy": null,
  "optimisation": false,
```
```bash
./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json \
-e output/fcfs-bb --enable-dynamic-jobs --enable-profile-reuse
```
 5. *sjf-bb*
```json
  "algorithm": "backfill",
  "future_burst_buffer_reservation": true,
  "priority_policy": "sjf",
  "optimisation": false,
```
```bash
./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json \
-e output/sjf-bb --enable-dynamic-jobs --enable-profile-reuse
```
 6. *plan-1*
```json
  "algorithm": "plan",
  "future_burst_buffer_reservation": true,
  "priority_policy": "sum",
  "optimisation": true,
```
```bash
./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json \
-e output/plan-1 --enable-dynamic-jobs --enable-profile-reuse
```
 7. *plan-2*
```json
  "algorithm": "plan",
  "future_burst_buffer_reservation": true,
  "priority_policy": "square",
  "optimisation": true,
```
```bash
./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json \
-e output/plan-2 --enable-dynamic-jobs --enable-profile-reuse
```
 8. *plan-3*
```json
  "algorithm": "plan",
  "future_burst_buffer_reservation": true,
  "priority_policy": "cube",
  "optimisation": true,
```
```bash
./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json \
-e output/plan-3 --enable-dynamic-jobs --enable-profile-reuse
```
For the truncated workloads, the first 5 algorithms should take about a minute to compute. Simulations with plan-based scheduling could take 30-60 minutes.

For the full workloads, the first 5 algorithms could take about a day to complete. Simulations with plan-based scheduling could take up to 4 days.

It is also possible to run experiments in parallel on the same machine. To do so, each experiment may be run with a different network port specified for communication between Batsim and Pybatsim. One may run Batsim and Pybatsim direcly, without using `./run_batsim_docker.sh` and `./run_pybatsim_git.sh` scripts.
```bash
PORT=20081

docker run --rm --net host -u $(id -u):$(id -g) -v $PWD:/data -m 9G oarteam/batsim:4.0.0 \
-s tcp://127.0.0.1:$PORT -p platforms/dragonfly96.xml \
-r node_0,node_9,node_18,node_27,node_36,node_45,node_54,node_63,node_72,node_81,node_90, node_99:storage \
-q -w workloads/KTH-SP2-1996-2.1-cln-io-aware-1000.json -e output/out \
--enable-dynamic-jobs --enable-profile-reuse &

source sim/bin/activate
python -O pybatsim/launcher.py -s tcp://127.0.0.1:$PORT -v warn -t 10000 burstbuffer/schedIOAware.py \
-O scheduler_options.json
```
To run another experiment, open second terminal window, update `scheduler_options.json`, change `PORT` number, specify different input workload and a different output path. 

### Split workloads
The last two Figues 11, 12 in the paper, were created using split workloads --- full workload split into 3-week parts. The split workloads are stored in `workloads/KTH-split/io-aware/`.
To automate running these experiments two scripts are available: `run_parts_serial.sh` and `run_parts_parallel.sh`. For a given policy, `run_parts_parallel.sh` runs all 16 parts in parallel, so we recommend to use it on a machine with at least 16 (virtual) cores. Otherwise, `run_parts_serial.sh` can be used, however running experiments with this sctipt will take very extensive time.
The scheduler config files can be found in `configs/` directory. Please note that the names of the config files differ from the scheduling names used in the paper. However, there is 1-1 mapping:

 - *filler* : filler
 - *fcfs* : fcfs
 - *fcfs-easy* : no-future-1
 - *fcfs-bb* : backfill-1
 - *sjf-bb* : backfill-sjf-1
 - *plan-1* : plan-opt-sum-0
 - *plan-2* : plan-opt-square-0
 - *plan-3* : plan-opt-cube-0

For example, to run split workloads for *sjf-bb* in parallel:
```bash
mkdir -p output/KTH-split/io-aware
./run_parts_parallel.sh io backfill-sjf-1
```
Please make sure that ports 28005-28020 are free. If something fails, kill all hanging docker and pybatsim processes.

**Step 11.** Run experiments with the split workloads for the above schedule configs.

### Analysing results
We prepared a jupyter notebook to generate Figure 3 and Figures 5-12.

**Step 12.** Download results for all experiments.
In case the full experiments takes too long time to recompute, we uploaded results of our experiments. They can be downloaded from the following link:
[https://1drv.ms/u/s!AnZ2wO-mAUeIgaE5K7o4f5HNbPFRtQ?e=E5tbOI](https://1drv.ms/u/s!AnZ2wO-mAUeIgaE5K7o4f5HNbPFRtQ?e=E5tbOI)
To unpack the results:
```
tar -xvf output.tar.gz
```
Then copy the results to corresponding directories in `Burst-Buffer-Scheduling/output`.

**Step 13.** Open jupyter notebook and generate plots.
```bash
source tools/bin/activate
cd analysis
jupyter notebook
```
Open the displayed link and navigate to `ArtifactEvaluation` notebook.

**Figure 3.** The Gantt chart presented in the paper in Figure 3. is based on a simulation with Alloc-Only model, as opposed to all other presented experiments which use IO-Aware simulation model. To reproduce this experiment set  `scheduler_options.json` according to *fcfs-easy* policy in Step 10. Then start the simulation with the following commands:
```bash
./run_batsim_docker.sh -w workloads/KTH-SP2-1996-2.1-cln-alloc-only.json -e output/my-no-future-1

./run_pybatsim_git.sh burstbuffer/schedAllocOnly.py scheduler_options.json
```

# Burst Buffer Scheduling (Old README, deprecated)

## Requirements
1. Batsim (3.1.0), using either Nix or Docker.
- Install Nix and Batsim.
```
curl https://nixos.org/nix/install | sh
source ~/nix-profiles/etc/profile.d/nix.sh
nix-env -f https://github.com/oar-team/nur-kapack/archive/master.tar.gz -iA batsim
```
- Install Docker. Batsim image will be downloaded on calling `run_batsim_docker.sh` script.
2. Pybatsim (master branch).
- ~`pip install pybatsim`~. Pip package does not contain latest changes with data staging fixed.
- `git clone git@gitlab.inria.fr:batsim/pybatsim.git` inside Burst-Buffer-Scheduling main directory.
3. Pandas <= 0.25.3
- `pip install pandas==0.25.3`
4. Evalys
- `pip install evalys`
5. Jupyter

## Running
### Batsim
- With Docker
```
./run_batsim_docker.sh platforms/two_nodes_bb_pfs.xml workloads/example_compute_with_bb.json
```
- Using Nix
```
batsim --enable-dynamic-jobs -e output/out -p platforms/two_nodes_bb_pfs.xml -w workloads/example_compute_with_bb.json
```
### Pybatsim
- Using cloned pybatsim repository
```
./run_pybatsim_git.sh schedulers/burstBufferScheduler.py
```
- Using Nix
```
pybatsim schedulers/burstBufferScheduler.py
```
### Analisys
```
jupyter notebook analysis/single_output.ipynb
```

## References
### Batsim
- https://batsim.readthedocs.io/en/latest/index.html
- https://gitlab.inria.fr/batsim/batsim/tree/master
- https://gitlab.inria.fr/batsim/batsim/issues/103
### Pybatsim
- https://gitlab.inria.fr/batsim/pybatsim
### Platforms
- https://simgrid.org/doc/latest/platform.html
- http://simgrid.gforge.inria.fr/simgrid/3.20/doc/platform.html
- https://simgrid.org/tutorials/simgrid-smpi-101.pdf
- https://framagit.org/simgrid/simgrid/tree/master/examples/platforms
- https://gitlab.inria.fr/batsim/bebida-on-batsim/tree/master/experiments/platforms
### Workloads
- https://www.cs.huji.ac.il/labs/parallel/workload/
### Analysis
- https://github.com/oar-team/evalys
- https://evalys.readthedocs.io/index.html
