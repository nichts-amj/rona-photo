$ErrorActionPreference = 'Stop'
$projectPath = Split-Path $PSScriptRoot -Parent
$sdkPath = Join-Path $PSScriptRoot 'vendor/sdk'
$outputPath = Join-Path $PSScriptRoot 'bin'
if (!(Test-Path (Join-Path $sdkPath 'lib/net462/Microsoft.Web.WebView2.Core.dll'))) {
    throw 'SDK WebView2 belum tersedia di desktop/vendor/sdk. Lihat desktop/README.md.'
}
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
& (Join-Path $projectPath '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'make_icon.py')
if ($LASTEXITCODE -ne 0) { throw 'Pembuatan ikon gagal.' }
Copy-Item (Join-Path $sdkPath 'lib/net462/Microsoft.Web.WebView2.Core.dll') $outputPath
Copy-Item (Join-Path $sdkPath 'lib/net462/Microsoft.Web.WebView2.WinForms.dll') $outputPath
Copy-Item (Join-Path $sdkPath 'runtimes/win-x64/native/WebView2Loader.dll') $outputPath
Copy-Item (Join-Path $PSScriptRoot 'rona.ico') $outputPath
& "$env:WINDIR/Microsoft.NET/Framework64/v4.0.30319/csc.exe" /nologo /target:winexe /platform:x64 `
    "/out:$outputPath/Rona Photo.exe" "/win32icon:$outputPath/rona.ico" `
    "/win32manifest:$PSScriptRoot/app.manifest" `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll `
    "/reference:$outputPath/Microsoft.Web.WebView2.Core.dll" "/reference:$outputPath/Microsoft.Web.WebView2.WinForms.dll" `
    (Join-Path $PSScriptRoot 'RonaDesktop.cs')
if ($LASTEXITCODE -ne 0) { throw 'Kompilasi launcher WebView gagal.' }
Copy-Item (Join-Path $PSScriptRoot 'app.config') (Join-Path $outputPath 'Rona Photo.exe.config')
Write-Output "Launcher WebView siap: $outputPath/Rona Photo.exe"
