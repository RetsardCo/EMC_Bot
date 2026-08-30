$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath ".\.venv\Scripts\Activate.ps1")) {
    throw "Virtual environment activation script was not found in $PSScriptRoot\.venv."
}

& ".\.venv\Scripts\Activate.ps1"
python ".\bot.py"
