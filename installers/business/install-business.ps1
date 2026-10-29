$ErrorActionPreference = 'Stop'
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install Python 3 from python.org, or open START-HERE.html for browser installation without Python.' }
& py -3 (Join-Path $PSScriptRoot 'setup.py') @args
if ($LASTEXITCODE -ne 0) { throw 'Business App setup failed. Review the message above.' }
