#!/bin/bash

# Activate local venv if it exists, otherwise use system python
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/.venv/bin/python"
PYTHON_SCRIPT="$SCRIPT_DIR/reader.py"

if [ -x "$VENV_PY" ]; then
	"$VENV_PY" "$PYTHON_SCRIPT"
else
	python3 "$PYTHON_SCRIPT"
fi