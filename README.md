# Burst Buffer Scheduling

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
- https://gitlab.inria.fr/batsim/bebida-on-batsim/tree/master/experiments/platforms
### Workloads
- https://www.cs.huji.ac.il/labs/parallel/workload/
### Analysis
- https://github.com/oar-team/evalys
- https://evalys.readthedocs.io/index.html
