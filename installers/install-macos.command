#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
python_bin=''
for candidate in python3.12 python3.13 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert sys.version_info[:2] in {(3,12),(3,13)}' >/dev/null 2>&1; then
    python_bin=$candidate
    break
  fi
done
if [ -z "$python_bin" ]; then
  echo 'Install Python 3.12 or 3.13 from python.org, then run this installer again.' >&2
  exit 1
fi
if [ "$#" -eq 0 ]; then
  "$python_bin" "$base/setup.py" --mode desktop --remote-isaac --directory "$HOME/Applications/RoboDE"
  echo 'Setup complete. Open ~/Applications/RoboDE/RoboDE.app to start.'
  printf 'Press Return to close this installer: '
  read -r answer
else
  exec "$python_bin" "$base/setup.py" --mode desktop --remote-isaac "$@"
fi
