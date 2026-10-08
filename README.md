# Rona Photo

Aplikasi pengeditan foto lokal untuk Windows 10/11 x64. Retouch, Adjust dengan area Orang/Latar dan Color/HSL, 32 Filter, Background, AI Edit, serta Upscale Real-ESRGAN/Swin2SR/HAT.

Kode sumber berada di repository ini. EXE dan komponen besar berada di **Releases**, tidak di riwayat Git.

## Pengguna aplikasi

Unduh paket awal dari Release v1.3, ekstrak seluruh isinya, lalu buka **Rona Photo.exe**. Pemasang menunjukkan kebutuhan unduhan sebelum dijalankan. Setelah runtime dan model lengkap, pemrosesan berjalan offline. Driver NVIDIA tetap diperlukan untuk GPU.

Repository private: tautan unduhan memerlukan login GitHub; pemasang tanpa login tidak dapat mengakses aset private. Unduh seluruh aset komponen secara manual dari halaman Releases dan letakkan ZIP komponen di samping EXE. Pemasang akan memakai salinan lokal dan memeriksa checksum.

Lihat [INSTALL](docs/INSTALL.md), [BUILD](docs/BUILD.md), dan [lisensi komponen](THIRD_PARTY_NOTICES.md).

## Pengembang

Gunakan Python 3.12 x64, buat `.venv`, lalu instal dependensi dari `requirements-lock.txt`. Bobot model tidak berada di repository; gunakan paket komponen rilis yang cocok atau skrip setup model dengan sumber/checksum yang dicatat di `models/*.json`.

Jalur browser: `start-studio.cmd`. Jalur WebView: `start-webview.cmd` setelah launcher dikompilasi. Riwayat dan foto pengguna tidak disertakan.

## Status

Versi aplikasi: **v1.3**. Pengujian fitur rilis dilakukan pengguna secara manual; tidak ada klaim telah diuji pada Windows bersih.

Lisensi aplikasi belum ditetapkan. Kode pihak ketiga dan model mempertahankan lisensi masing-masing; repository public tidak otomatis berarti seluruh paket boleh dipakai secara komersial.
