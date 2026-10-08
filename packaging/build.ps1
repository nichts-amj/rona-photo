$ErrorActionPreference = 'Stop'
$projectPath = Split-Path $PSScriptRoot -Parent
$releasePath = Join-Path (Split-Path $projectPath -Parent) 'Rona Photo v1.0'
& (Join-Path $projectPath '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'build_portable.py')
if ($LASTEXITCODE -ne 0) { throw 'Build folder failed; existing releases are never overwritten.' }
& "$env:WINDIR/Microsoft.NET/Framework64/v4.0.30319/csc.exe" /nologo /target:winexe /platform:x64 "/out:$releasePath/Rona Photo.exe" "/win32icon:$releasePath/rona.ico" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll (Join-Path $PSScriptRoot 'Launcher.cs')
if ($LASTEXITCODE -ne 0) { throw 'EXE compilation failed.' }
& (Join-Path $releasePath 'runtime/python.exe') -I -B (Join-Path $PSScriptRoot 'validate_portable.py') $releasePath
if ($LASTEXITCODE -ne 0) { throw 'Portable runtime validation failed.' }
