$ErrorActionPreference = 'Stop'
# Run as the Windows user who will run the application, not as SYSTEM.
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install Python 3.12 from python.org with the Python launcher, then rerun setup.' }
& py -3.12 -c 'import sys; assert sys.version_info[:2] == (3,12)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required. Install it before running this installer.' }
& py -3.12 (Join-Path $PSScriptRoot 'setup.py') --mode desktop @args
if ($LASTEXITCODE -ne 0) { throw "Robot IDE installation failed. Review the message above." }
