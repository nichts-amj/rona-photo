param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force -Path $OutputPath | Out-Null
$repo=Split-Path $PSScriptRoot -Parent
& "$env:WINDIR/Microsoft.NET/Framework64/v4.0.30319/csc.exe" /nologo /target:winexe /platform:x64 "/out:$OutputPath/Rona Photo.exe" "/win32icon:$repo/desktop/rona.ico" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'Bootstrap.cs')
if($LASTEXITCODE -ne 0){throw 'Bootstrap compilation failed.'}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install-components.ps1') -Destination $OutputPath
Copy-Item -LiteralPath (Join-Path $repo 'desktop/rona.ico') -Destination $OutputPath
