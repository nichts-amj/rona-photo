# Build dan distribusi

## Jalur pengembangan

Instal Python 3.12 x64, buat `.venv` dan instal `requirements-lock.txt`. Model besar disimpan di `models` secara lokal. SDK WebView2 perlu tersedia di `desktop/vendor/sdk` sesuai `desktop/README.md`, lalu jalankan `desktop/build.ps1`.

## Paket GitHub

`release-tools/package_components.py --portable-dir PATH --output PATH` mengambil folder portable yang sudah lengkap dan memisahkannya menjadi aplikasi, runtime, model inti, model AI Edit, dan prasyarat. Komponen dibagi menjadi beberapa ZIP di bawah batas 2 GiB GitHub. Versi komponen didasarkan pada isi sehingga komponen yang tidak berubah dapat digunakan kembali.

Kompilasi bootstrap melalui `release-tools/build-bootstrap.ps1 -OutputPath PATH`. Masukkan EXE bootstrap, installer PowerShell, components.json dan Panduan.txt ke paket awal.

Publisher harus mengisi URL aset nyata dalam components.json setelah upload selesai. Paket komponen diunggah ke release komponen dan paket awal/aplikasi ke release v1.3. Jangan menerbitkan manifest yang masih memakai URL kosong.

Build lengkap v1.3 dibuat memakai staging terpisah; skrip `packaging` lama di repository adalah jalur historis dan belum menjadi build portable otomatis terbaru. Snapshot sumber bukan pengganti paket runtime/model.
