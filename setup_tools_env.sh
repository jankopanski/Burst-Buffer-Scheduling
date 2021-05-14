#!/usr/bin/env bash

set -e # Terminate script on error
set -x # Print commands

virtualenv -p python3.8 tools
source tools/bin/activate
pip install --upgrade pip
pip install --upgrade setuptools
pip install -r tools-requirements.txt

