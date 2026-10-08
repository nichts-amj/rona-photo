# Optimasi Upscale proyek pengembangan

Cadangan sebelum perubahan: `backups/upscale-sebelum-optimasi_2026-10-07_01-08-43`.
EXE rilis v1.1 tidak diperbarui.

- Jalur Studio CUDA memakai mixed precision: FP16 untuk Real-ESRGAN;
  BF16 untuk Swin2SR/HAT jika GPU mendukungnya. CPU dan GPU lama tetap FP32.
  Bobot asli tidak diubah. Nilai piksel dapat sedikit berbeda dari FP32.
- Jika keluaran mixed precision mengandung NaN/Inf, proses diulang dalam FP32.
  Pembatalan dan kesalahan lain tetap diteruskan, bukan disembunyikan.
- Potongan menyesuaikan memori GPU yang tersedia, dengan nilai pengaturan
  sebagai batas maksimum. Context Real-ESRGAN 34 px dan HAT 32 px tetap.
  Overlap Swin tetap; fallback OOM melewati ukuran yang terlalu kecil untuk overlap.
  Resolusi input dan skala keluaran 2×/4× tidak diperkecil oleh optimasi ini.
- Hanya satu model disimpan di GPU selama antrean. Model yang sama dipakai ulang
  antar-foto/skala, lalu dilepas saat pergantian model/denoise, selesai, dibatalkan,
  gagal, atau aplikasi ditutup. Retouch dan AI Edit melepasnya sebelum mulai.
- Pemeriksaan NaN/Inf dilakukan pada buffer hasil yang sudah dipindahkan ke CPU,
  menghilangkan satu penantian GPU tambahan untuk setiap potongan.
- Cache hasil mixed precision dipisahkan dari cache FP32 lama.

## Catatan waktu

`processing.json` dan tombol Catatan parameter memuat waktu membaca sumber,
menyiapkan model, menjalankan model, menyimpan PNG, dan menggabungkan hasil.
Catatan per-model mencakup `engine_reused`, presisi, fallback, potongan aktual,
serta `timings` per potongan: unggah, enqueue forward, unduh/menunggu,
penggabungan CPU, dan waktu komputasi CUDA melalui event.

Waktu komputasi CUDA beririsan dengan waktu menunggu unduhan; jangan jumlahkan
keduanya. Waktu model awal juga mencakup pembacaan/pemeriksaan bobot.
Waktu PNG dan penggabungan tetap memakai CPU. Tidak ada klaim peningkatan
kecepatan tertentu sebelum mengukur foto yang sama pada perangkat pengguna.

Untuk pembandingan FP32 melalui konfigurasi API, set `gpu_optimization: false`.
Adapter langsung/skrip validasi tetap FP32 secara default; optimasi aktif melalui Studio.
