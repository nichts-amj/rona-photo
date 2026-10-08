param([Parameter(Mandatory=$true)][string]$PythonExe)
$ErrorActionPreference = 'Stop'
$environmentPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $environmentPython)) {
    & $PythonExe -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Pembuatan venv gagal.' }
}
$lock = Join-Path $PSScriptRoot 'requirements-lock.txt'
if (-not (Test-Path -LiteralPath $lock)) { $lock = Join-Path $PSScriptRoot 'requirements-sr.txt' }
& $environmentPython -m pip install -r $lock --extra-index-url https://download.pytorch.org/whl/cu126
if ($LASTEXITCODE -ne 0) { throw 'Instalasi dependensi gagal.' }
& $environmentPython (Join-Path $PSScriptRoot 'setup_model.py')
if ($LASTEXITCODE -ne 0) { throw 'Pengunduhan/verifikasi model gagal.' }
& $environmentPython (Join-Path $PSScriptRoot 'doctor.py') --probe-cuda
exit $LASTEXITCODE
