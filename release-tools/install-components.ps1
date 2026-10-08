param([string]$Root = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$installRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
$manifest = Get-Content -LiteralPath (Join-Path $Root 'components.json') -Raw | ConvertFrom-Json
$downloads = Join-Path $Root '.downloads'
$markers = Join-Path $Root '.components'
New-Item -ItemType Directory -Force -Path $downloads,$markers | Out-Null
try {
  foreach ($component in $manifest.components) {
    $marker = Join-Path $markers ($component.id + '.ready')
    if (Test-Path -LiteralPath $marker) { continue }
    foreach ($asset in $component.assets) {
      if ([IO.Path]::GetFileName($asset.name) -ne $asset.name) { throw 'Nama paket tidak valid.' }
      $local = Join-Path $Root $asset.name
      $cached = Join-Path $downloads $asset.name
      if (Test-Path -LiteralPath $local) { $archivePath = $local }
      else {
        $archivePath = $cached
        if (!(Test-Path -LiteralPath $cached)) {
          if (!$asset.url) { throw 'URL belum tersedia. Unduh ZIP komponen dari Releases dan letakkan di samping EXE.' }
          $uri = [Uri]$asset.url
          if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'github.com') { throw 'Sumber unduhan harus GitHub HTTPS.' }
          Write-Output ('Mengunduh ' + $component.label + ': ' + $asset.name)
          $partial = $cached + '.part'
          $offset = 0
          if (Test-Path -LiteralPath $partial) {
            if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLower() -eq $asset.sha256) {
              Move-Item -LiteralPath $partial -Destination $cached
            } else { $offset = (Get-Item -LiteralPath $partial).Length }
          }
          if (!(Test-Path -LiteralPath $cached)) {
            $request = [Net.HttpWebRequest]::Create($asset.url)
            $request.UserAgent = 'Rona-Photo-Installer'
            $request.Timeout = 120000
            $request.ReadWriteTimeout = 120000
            if ($offset -gt 0) { $request.AddRange([long]$offset) }
            $response = $request.GetResponse()
            $append = $offset -gt 0 -and [int]$response.StatusCode -eq 206
            $mode = if ($append) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $inputStream = $response.GetResponseStream()
            $outputStream = [IO.File]::Open($partial, $mode, [IO.FileAccess]::Write)
            try { $inputStream.CopyTo($outputStream, 1048576) }
            finally { $outputStream.Dispose(); $inputStream.Dispose(); $response.Dispose() }
            Move-Item -LiteralPath $partial -Destination $cached
          }
        }
      }
      Write-Output ('Memeriksa ' + $asset.name)
      if ((Get-Item -LiteralPath $archivePath).Length -ne $asset.bytes -or (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLower() -ne $asset.sha256) {
        throw ('Checksum tidak cocok: ' + $asset.name + '. Ganti ZIP ini dengan unduhan yang utuh.')
      }
      Write-Output ('Memasang ' + $component.label)
      $zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
      try {
        foreach ($entry in $zip.Entries) {
          $destination = [IO.Path]::GetFullPath((Join-Path $Root $entry.FullName))
          if (!$destination.StartsWith($installRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Jalur arsip keluar dari folder aplikasi.' }
          if (($entry.ExternalAttributes -shr 16 -band 61440) -eq 40960) { throw 'Link simbolik tidak diizinkan.' }
          if (!$entry.Name) { New-Item -ItemType Directory -Force -Path $destination | Out-Null; continue }
          New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($destination)) | Out-Null
          [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$destination,$true)
        }
      } finally { $zip.Dispose() }
    }
    Set-Content -LiteralPath $marker -Value $component.id -Encoding ASCII
  }
  Write-Output 'Komponen lengkap. Membuka Rona Photo...'
  exit 0
} catch {
  Write-Output ('Pemasangan belum selesai: ' + $_.Exception.Message)
  Write-Output 'Untuk repository private, unduh ZIP melalui GitHub yang sudah login, lalu letakkan di samping EXE. Tekan Siapkan komponen untuk melanjutkan.'
  exit 1
}
