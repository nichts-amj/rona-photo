# Pemasangan

1. Ekstrak paket awal di folder lokal yang dapat ditulis.
2. Buka Rona Photo.exe. Jika komponen belum tersedia, pemasang menampilkan versi dan perkiraan unduhan. Klik **Siapkan komponen**.
3. Unduhan disimpan sementara, dapat dilanjutkan, lalu diperiksa SHA-256 sebelum diekstrak.
4. Setelah lengkap, launcher membuka aplikasi WebView. Pemrosesan foto tidak memerlukan koneksi internet.

## Private / offline

Unduh semua ZIP komponen yang tercantum di `components.json` ke folder yang sama dengan EXE sebelum menekan Siapkan komponen. Untuk rilis private, gunakan halaman Releases ketika sudah login. Tidak ada token yang dibundel dalam aplikasi.

ZIP lokal tetap diperiksa checksum. Setelah pemasangan selesai, ZIP dapat dipindahkan untuk menghemat ruang. Sisakan ruang untuk ZIP dan hasil ekstraksi; runtime, model dan aplikasi terpasang membutuhkan sekitar 9,7 GB, ditambah ruang untuk data pengguna.

## Pembaruan

Runtime dan model mempunyai versi komponen tersendiri. Versi aplikasi berikutnya dapat memakai kembali komponen yang identik; cukup mengganti paket aplikasi. Jangan mencampur manifest dari versi berbeda.

GPU memerlukan driver NVIDIA yang kompatibel dengan CUDA 12.6; CUDA Toolkit terpisah tidak diperlukan. Installer offline .NET 4.8 dan Visual C++ disertakan dalam komponen prasyarat bila Windows membutuhkannya.

Pengujian instalasi, seluruh fitur dan pemrosesan foto masih menunggu uji manual pengguna.
