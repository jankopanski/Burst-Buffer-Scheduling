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
