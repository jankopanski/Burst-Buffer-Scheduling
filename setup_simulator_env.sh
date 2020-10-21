#!/usr/bin/env bash

wget https://downloads.python.org/pypy/pypy3.7-v7.3.2-linux64.tar.bz2
tar xf pypy3.7-v7.3.2-linux64.tar.bz2
virtualenv -p pypy3.7-v7.3.2-linux64/bin/pypy sim
source sim/bin/activate
pip install -r simulator-requirements.txt