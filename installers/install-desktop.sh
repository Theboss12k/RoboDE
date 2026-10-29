#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3.12 >/dev/null 2>&1; then
  echo "Install Python 3.12 and its venv package first: sudo apt install python3.12 python3.12-venv" >&2
  exit 1
fi
exec python3.12 "$base/setup.py" --mode desktop "$@"
