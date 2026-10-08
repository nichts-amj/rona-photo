# Jalur desktop Rona Photo (pengembangan Windows x64)

- `start-webview.cmd` membuka `desktop/bin/Rona Photo.exe`: splash → UI WebView2.
- `start-studio.cmd` tetap membuka UI melalui browser. File itu tidak diubah.
- Keduanya menggunakan server loopback port 8772 dan folder data Studio yang sama.
- Jika server browser sudah berjalan dengan versi kode yang sama, WebView memakainya tanpa membuat server baru. Menutup WebView tidak menutup server browser tersebut.
- Jika WebView memulai server sendiri, penutupan jendela menghentikan server itu melalui endpoint khusus dengan kunci acak. Saat AI masih aktif, penutupan ditolak: tunggu selesai atau Cancel dahulu.
- Jangan menutup jendela ketika masih ada perubahan foto yang belum di-Save. Riwayat yang sudah disimpan tetap tersedia pada kedua jalur.

## Launcher dan splash

Launcher dibangun memakai WinForms (.NET Framework) dan SDK WebView2 resmi Microsoft. Wallpaper splash mengikuti tema terakhir WebView; pembukaan pertama memakai tema siang. Splash menampilkan logo, judul Rona Photo, status dan bar loading tanpa keterangan modul. Bar bergerak tanpa persentase palsu dan status diperbarui saat pemeriksaan WebView2, persiapan server, dan pembukaan halaman.

Splash ditutup setelah halaman utama selesai menyiapkan bootstrap, font, wallpaper, dan frame tampilan pertama. Model AI tidak dijalankan saat membuka launcher. Saat gagal, loading berhenti dan dua ikon Coba lagi/Tutup aplikasi muncul sejajar di tengah bawah pesan, dengan tooltip dan label aksesibilitas. Jendela kedua mengaktifkan jendela Rona yang sudah ada.

Saat tombol × Windows ditekan, overlay "Menutup Rona Photo…" dengan loading muncul sebelum permintaan shutdown dan penantian proses server selesai. Klik tutup berulang diabaikan selama pemeriksaan. Jika proses AI masih aktif atau shutdown gagal, overlay dipulihkan ke keadaan sebelumnya dan workspace bisa digunakan kembali. Server milik jalur browser tetap berjalan saat WebView ditutup.

Tema dan glass tersimpan pada profil WebView di `%LOCALAPPDATA%/Rona Photo/WebView/<id-proyek>`. Profil WebView terpisah dari profil Chrome/Edge: preferensi browser tidak otomatis disalin pada pembukaan WebView pertama. Foto, cache model, preset pemrosesan dan Riwayat tetap berasal dari folder Studio yang sama. Cache grid sesi tetap mengikuti aturan UI yang ada.

Pemilihan foto memakai dialog file WebView2. Unduh/Export memakai dialog Simpan Windows. Navigasi aplikasi tetap lokal; tautan situs eksternal hanya dibuka atas klik pengguna. Tidak ada pembukaan browser otomatis oleh jalur WebView.

## Build ulang launcher

Jalankan `desktop/build.ps1` setelah mengubah kode C# launcher. Perubahan UI/Python langsung dipakai saat server dimulai ulang; tidak memerlukan kompilasi ulang launcher.

SDK sudah tersedia di `desktop/vendor/sdk`, dengan versi di `desktop/vendor/version.txt`. SDK diunduh dari paket `Microsoft.Web.WebView2` resmi NuGet. Build memakai kompilator Windows `.NET Framework64/v4.0.30319/csc.exe` dan `.venv` proyek untuk membuat ikon.

WebView2 Runtime harus tersedia. Komputer pengembangan ini sudah memilikinya. Jika tidak tersedia di komputer lain, launcher menampilkan petunjuk; jalur browser masih bisa digunakan. Panduan distribusi runtime: https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution

Ini **launcher pengembangan**, bukan paket rilis portable baru. EXE tetap memerlukan folder proyek, `.venv`, model, UI, dan dependensi yang sekarang. `packaging/Launcher.cs`, build rilis lama, dan folder rilis sebelumnya tidak diubah. Paket rilis WebView mandiri dibuat pada tahap rilis terpisah.

`Rona Photo.exe --render-splash` membuat `desktop/splash-preview.png` tanpa memulai server atau menjalankan model.

Launcher memakai .NET Framework 4.8. Manifest EXE mengaktifkan Per-Monitor V2 sejak proses dimulai; pemeriksaan dan fallback native dilakukan sebelum pemanggilan WinForms atau pembuatan jendela. `app.config` tetap mengaktifkan dukungan DPI WinForms dan disalin ke sebelah EXE. `Rona Photo.exe --check-dpi` memeriksa konteks DPI thread sebelum jendela dibuat dan menulis hasil ke `desktop/dpi-check.json` (exit 0 jika Per-Monitor V2 aktif). Jangan memisahkan EXE dari `.exe.config` dan DLL-nya.
