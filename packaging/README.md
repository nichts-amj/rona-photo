# Rona Photo v1.0 Windows x64

Build folder terpisah dari proyek pengembangan. Jalankan build.ps1 untuk membuat ulang; script menolak menimpa folder rilis yang sudah ada. Build menggunakan Python standalone dari base interpreter beserta dependency closure venv, bukan menyalin venv dengan path absolut. python312._pth mengisolasi registry, user site, dan PYTHONPATH. EXE pembuka dikompilasi dari Launcher.cs menggunakan C#/.NET Framework Windows.

Resource models/web/third_party berada di root rilis. Kode program ada di app. Data pengguna portable menggunakan LOCALAPPDATA/Rona Photo/studio, terpisah dari outputs/studio pengembangan. Server portable 8773; pengembangan 8772.

63 tes regresi lulus. Runtime paket berhasil memuat checkpoint keenam model secara strict di CPU; HTTP bootstrap/riwayat/aset sukses. Pemeriksaan tensor CUDA berhasil pada RTX 3050. Pemeriksaan --cpu berhasil. Launcher dikompilasi x64 versi 1.0.0.0, tanpa tanda tangan digital.

Tidak menguji interaksi GUI sesuai preferensi pengguna. Belum diuji pada mesin/VM Windows bersih yang tidak memiliki Python, CUDA Toolkit, atau VC++ Runtime. Windows memerlukan driver NVIDIA kompatibel untuk GPU, .NET Framework 4.8 untuk launcher, dan mungkin VC++ Redistributable x64 untuk PyTorch. Tidak memasang atau mengubah driver/CUDA/Python sistem.

CodeFormer membatasi redistribusi/penggunaan nonkomersial; paket ini untuk penelitian/nonkomersial. Lisensi model dan dependensi dibawa di paket. Jangan menyebut paket ini berlisensi komersial universal.

Arsip dibuat dengan archive_release.py (ZIP64, deflate level 1) dan SHA-256. Jangan mengubah folder rilis selama pengarsipan. Uji pada komputer tujuan sebelum mendistribusikan luas.
