#!/usr/bin/env bash
# One-shot installer for matchup: creates the conda environment, installs the
# package, and verifies that every piece actually works.
#
#   ./install.sh              # create/update env 'matchup', install, check
#   ./install.sh myenvname    # same, with a different environment name
#
# Safe to re-run: an existing environment is updated, not destroyed.
set -euo pipefail

ENV_NAME="${1:-matchup}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== matchup installer"
echo "    repo:        $HERE"
echo "    environment: $ENV_NAME"
echo

# 1. conda present?
if ! command -v conda >/dev/null 2>&1; then
    echo "ERROR: conda not found in PATH."
    echo "Install Miniforge (https://conda-forge.org/download/) and run this again."
    exit 1
fi
echo "--- conda: $(conda --version)"

# `conda activate` inside a script needs the shell hook.
eval "$(conda shell.bash hook)"

# 2. create or update the environment
if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    echo "--- environment '$ENV_NAME' exists: updating it"
    conda env update -n "$ENV_NAME" -f "$HERE/environment.yml" --prune
else
    echo "--- creating environment '$ENV_NAME' (this takes a few minutes)"
    conda env create -n "$ENV_NAME" -f "$HERE/environment.yml"
fi

conda activate "$ENV_NAME"

# 3. install matchup itself (editable: edits to src/ take effect immediately)
echo "--- installing matchup"
pip install -q -e "$HERE"

# 4. verify
echo
echo "--- checking the installation"
if matchup doctor; then
    echo
    echo "=== SUCCESS"
    echo
    echo "Use it in a new terminal with:"
    echo "    conda activate $ENV_NAME"
    echo "    matchup --help"
    echo
    echo "Next: copy config/campaigns/harry.yaml, point it at your data,"
    echo "then run   matchup scan <your-campaign>.yaml"
    echo "See README_STANDALONE.md."
else
    echo
    echo "=== INSTALLATION INCOMPLETE -- see the failures above."
    exit 1
fi
