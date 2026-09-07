#!/usr/bin/env bash
# Create or update the FieldMatch conda environment and install this checkout.
set -euo pipefail

ENV_NAME="${1:-fieldmatch}"
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v conda >/dev/null 2>&1; then
    echo "conda was not found; install Miniforge or add conda to PATH" >&2
    exit 1
fi

eval "$(conda shell.bash hook)"
if conda env list | awk '{print $1}' | grep -Fxq "$ENV_NAME"; then
    conda env update --name "$ENV_NAME" --file "$ROOT_DIR/environment.yml" --prune
else
    conda env create --name "$ENV_NAME" --file "$ROOT_DIR/environment.yml"
fi

conda activate "$ENV_NAME"
python -m pip install --editable "$ROOT_DIR"
fieldmatch doctor

echo
echo "FieldMatch is ready. Activate it with: conda activate $ENV_NAME"
echo "Then run: fieldmatch --help"
