$ErrorActionPreference = 'Stop'
$attentionRoot = Split-Path -Parent $PSScriptRoot
$attentionPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (!(Test-Path -LiteralPath $attentionPython)) {
    $attentionPython = (Get-Command python -ErrorAction Stop).Source
}
Push-Location -LiteralPath $attentionRoot
try {
    & $attentionPython -m venv tools/research-env
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create simulation Python environment.' }
    & './tools/research-env/Scripts/python.exe' -m pip install -r requirements-simulation.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Cannot install synthesis dependencies.' }
    if (!(Test-Path -LiteralPath 'tools/msys2/ucrt64/bin/iverilog.exe')) {
        & './tools/research-env/Scripts/python.exe' -m pip install zstandard==0.25.0
        if ($LASTEXITCODE -ne 0) { throw 'Cannot install archive decompressor.' }
        & './tools/research-env/Scripts/python.exe' scripts/fetch_iverilog.py
        if ($LASTEXITCODE -ne 0) { throw 'Cannot prepare Icarus Verilog.' }
    }
    Write-Host 'Simulation environment ready.'
} finally {
    Pop-Location
}
