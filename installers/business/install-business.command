#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
python3 "$base/setup.py" "$@"
if [ "$#" -eq 0 ]; then
  printf 'Press Return to close: '
  read -r answer
fi
