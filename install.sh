#!/usr/bin/env bash
# One-shot installer for matchup: creates the conda environment, installs the
# package, and verifies that every piece actually works.
#
#   ./install.sh              # create/update env 'matchup', install, check
#   ./install.sh myenvname    # same, with a different environment name
#
# Safe to re-run: an existing environment is updated, not destroyed. Two runs
# cannot overlap (see the lock below), and conda is bounded by a timeout so a
# stalled download fails with a message instead of hanging forever.
#
# Environment overrides:
#   MATCHUP_CONDA_TIMEOUT=3600   seconds allowed for the conda step
set -euo pipefail

ENV_NAME="${1:-matchup}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_TIMEOUT="${MATCHUP_CONDA_TIMEOUT:-3600}"

echo "=== matchup installer"
echo "    repo:        $HERE"
echo "    environment: $ENV_NAME"
echo

# ---------------------------------------------------------------------------
# 1. conda present?
# ---------------------------------------------------------------------------
if ! command -v conda >/dev/null 2>&1; then
    echo "ERROR: conda not found in PATH."
    echo "Install Miniforge (https://conda-forge.org/download/) and run this again."
    exit 1
fi
echo "--- conda: $(conda --version)"

# `conda activate` inside a script needs the shell hook.
eval "$(conda shell.bash hook)"

# ---------------------------------------------------------------------------
# 2. only one installer at a time for this environment.
#    Two concurrent creates write to the same prefix and leave it half-built
#    (and the loser can wedge in uninterruptible I/O). An advisory lock is the
#    reliable guard; the pgrep check below additionally catches a conda run
#    started BY HAND outside this script.
# ---------------------------------------------------------------------------
LOCKFILE="${TMPDIR:-/tmp}/matchup-install-${ENV_NAME}.lock"
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCKFILE" || true
    if ! flock -n 9; then
        echo "ERROR: another ./install.sh for '$ENV_NAME' is already running."
        echo "Wait for it to finish (lock: $LOCKFILE)."
        exit 1
    fi
fi
if pgrep -af conda 2>/dev/null | grep -F -- "$ENV_NAME" | grep -vq "install.sh"; then
    echo "ERROR: a conda operation mentioning '$ENV_NAME' is already running:"
    pgrep -af conda | grep -F -- "$ENV_NAME" | grep -v "install.sh" | sed 's/^/    /'
    echo
    echo "Wait for it to finish, or stop it and clean up:"
    echo "    conda env remove -n $ENV_NAME"
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. is there a half-built environment from an interrupted run?
#    A partial prefix exists on disk but conda does not list it, so a plain
#    create would fail with a confusing 'prefix already exists'.
# ---------------------------------------------------------------------------
env_is_registered() {
    conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"
}
PREFIX="$(conda info --base)/envs/$ENV_NAME"
if [ -d "$PREFIX" ] && ! env_is_registered; then
    echo "ERROR: '$PREFIX' exists but conda does not list it as an environment."
    echo "That is a half-built environment from an interrupted run. Remove it:"
    echo "    conda env remove -n $ENV_NAME    # or: rm -rf '$PREFIX'"
    echo "then run this script again."
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. create or update the environment, bounded by a timeout.
#    --solver=libmamba explicitly: `conda env create` does not always inherit
#    the configured solver, and the classic one is far slower on this spec.
# ---------------------------------------------------------------------------
SOLVER_FLAG=""
if conda env create --help 2>&1 | grep -q -- "--solver"; then
    SOLVER_FLAG="--solver=libmamba"
fi
TIMEOUT_CMD=()
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_CMD=(timeout --foreground "${CONDA_TIMEOUT}s")
fi

on_interrupt() {
    echo
    echo "!!! interrupted. If the environment is half-built, remove it before"
    echo "    retrying:   conda env remove -n $ENV_NAME"
    exit 130
}
trap on_interrupt INT TERM

set +e
if env_is_registered; then
    echo "--- environment '$ENV_NAME' exists: updating it"
    "${TIMEOUT_CMD[@]}" conda env update -n "$ENV_NAME" \
        -f "$HERE/environment.yml" --prune $SOLVER_FLAG
else
    echo "--- creating environment '$ENV_NAME'"
    echo "    (several minutes; most of it is downloading eccodes and netcdf)"
    "${TIMEOUT_CMD[@]}" conda env create -n "$ENV_NAME" \
        -f "$HERE/environment.yml" $SOLVER_FLAG
fi
CONDA_RC=$?
set -e
trap - INT TERM

if [ "$CONDA_RC" -eq 124 ]; then
    echo
    echo "ERROR: conda exceeded ${CONDA_TIMEOUT}s and was stopped."
    echo "Usually a stalled package download. Remove the partial environment"
    echo "and retry, allowing more time if your connection is slow:"
    echo "    conda env remove -n $ENV_NAME"
    echo "    MATCHUP_CONDA_TIMEOUT=7200 ./install.sh $ENV_NAME"
    exit 1
elif [ "$CONDA_RC" -ne 0 ]; then
    echo
    echo "ERROR: conda failed (exit $CONDA_RC) -- see the output above."
    echo "If the environment was left half-built:  conda env remove -n $ENV_NAME"
    exit 1
fi

conda activate "$ENV_NAME"

# ---------------------------------------------------------------------------
# 5. install matchup itself (editable: edits to src/ take effect immediately)
# ---------------------------------------------------------------------------
echo "--- installing matchup"
if ! "${TIMEOUT_CMD[@]}" pip install -q -e "$HERE"; then
    echo "ERROR: pip install failed or timed out."
    exit 1
fi

# ---------------------------------------------------------------------------
# 6. verify
# ---------------------------------------------------------------------------
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
