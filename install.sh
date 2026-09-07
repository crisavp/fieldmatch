#!/usr/bin/env bash
# Install this source folder. Never update/prune an existing conda environment.
set -euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
usage() {
    echo "Usage: $0 --existing | --new [environment-name]"
    echo "  --existing: use the active Python environment, install FieldMatch + plotting"
    echo "  --new: create a new conda environment (default: fieldmatch), then install"
}
case "${1:---help}" in
    --help|-h) usage; exit 0 ;;
    --existing)
        if (( $# != 1 )); then usage >&2; exit 2; fi
        command -v python >/dev/null || { echo "Activate your Python environment first." >&2; exit 1; }
        python -m pip install "${ROOT_DIR}[plot]"
        python -m fieldmatch.cli doctor
        ;;
    --new)
        if (( $# > 2 )); then usage >&2; exit 2; fi
        command -v conda >/dev/null || { echo "Install conda/Miniforge or use --existing." >&2; exit 1; }
        STUDY_ENV_NAME="${2:-fieldmatch}"
        conda env create --name "$STUDY_ENV_NAME" --file "$ROOT_DIR/environment.yml"
        conda run --name "$STUDY_ENV_NAME" python -m pip install "${ROOT_DIR}[plot]"
        conda run --name "$STUDY_ENV_NAME" python -m fieldmatch.cli doctor
        echo "Activate with: conda activate $STUDY_ENV_NAME"
        ;;
    *) usage >&2; exit 2 ;;
esac
