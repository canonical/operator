#!/bin/bash

# Update and freeze docs/requirements.txt from docs/requirements.in

set -ex

python3 -m venv docsenv
source docsenv/bin/activate
pip install -r docs/requirements.in
pip freeze >docs/requirements.txt
deactivate
rm -rf docsenv
