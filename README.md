# 🤖 AutoAbsen ETHOL PENS - Telegram Bot

Bot otomatisasi presensi perkuliahan di sistem ETHOL PENS dengan integrasi laporan langsung ke Telegram. Dirancang khusus untuk berjalan 24/7 di Ubuntu VM (Proxmox).

---

## 📋 Fitur Utama
- **Autentikasi CAS SSO Otomatis**: Menangani login SSO PENS dan otomatis login ulang saat session kedaluwarsa.
- **Deteksi Presensi Real-Time**: Memeriksa lonceng notifikasi dan status sesi perkuliahan aktif secara berkala.
- **Notifikasi Otomatis Tugas & Materi Baru**: Secara otomatis mendeteksi dan mengirim pesan notifikasi ke Telegram saat dosen mengunggah tugas baru atau materi kuliah baru di ETHOL.
- **Anti Double-Presensi**: Menyimpan history sesi yang sudah diabsen di `attended_keys.json` untuk mencegah spamming.
- **Laporan Telegram Komprehensif**:
  - Nama Mata Kuliah
  - Nama Dosen Pengampu & Gelar
  - Jam Presensi Dibuka oleh Dosen (waktu real-time & relatif)
  - Jam Eksekusi Presensi oleh Bot
  - Status Keberhasilan Presensi
- **Pengumpulan Tugas Kuliah via Telegram**:
  - Memilih mata kuliah & judul tugas langsung lewat tombol interaktif di Telegram.
  - Cukup kirim file dokumen (PDF, Word, Zip, dsb.) ke chat bot -> Bot otomatis mengunggah file ke sistem ETHOL.
- **Monitoring & Kontrol Server VM**:
  - Menampilkan seluruh IP interface (eth0, tailscale0, dsb.).
  - Uji ping koneksi internet (ETHOL, Telegram, Google, Cloudflare).
  - Monitoring penggunaan RAM Memory (%) dan Disk.
  - Tombol Reboot / Restart Ubuntu VM langsung dari Telegram dengan konfirmasi keamanan.
- **Menu & Tombol Interaktif di Telegram**:
  - `/status` atau Tombol `📊 Status` : Menampilkan informasi bot, akun aktif, NRP, rata-rata kehadiran semester berjalan, total mata kuliah, dan status koneksi ETHOL.
  - `/tugas` atau Tombol `📝 Tugas` : Menampilkan daftar seluruh tugas kuliah yang belum dikumpulkan, dikelompokkan rapi per mata kuliah & dosen, dilengkapi tombol navigasi halaman (`Prev` / `Next`).
  - `/kumpul` atau Tombol `📤 Kumpulkan Tugas` : Membuka alur pengumpulan tugas kuliah ke ETHOL.
  - `/server` atau Tombol `🖥️ Info Server & VM` : Menampilkan diagnostik IP, ping internet, RAM %, dan tombol reboot VM.
  - `/menu` : Menampilkan menu utama navigasi interaktif.
- **Background Service (Systemd)**: Dapat dijalankan sebagai service sistem Linux, otomatis hidup saat VM booting dan auto-restart jika ada gangguan jaringan.

---

## 🚀 Panduan Instalasi & Menjalankan di Ubuntu VM

### 1. Masuk ke Direktori Project
```bash
cd /home/ary/autoabsen
```

### 2. Pasang Dependensi Python
Kamu bisa menggunakan environment sistem atau virtualenv:

```bash
# (Opsional) Membuat virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependensi yang dibutuhkan
pip install -r requirements.txt
```

### 3. Konfigurasi Kredensial & Topik Forum (.env)
Salin file `.env.example` ke `.env` lalu sesuaikan kredensial Anda:
```ini
ETHOL_EMAIL=your_email@student.pens.ac.id
ETHOL_PASSWORD=your_sso_password
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_group_or_chat_id
CHECK_INTERVAL_SECONDS=30
TIMEZONE=Asia/Jakarta

# (Opsional) ID Topik Forum Telegram jika menggunakan Supergroup Topics
TOPIC_PRESENSI_ID=
TOPIC_MATERI_ID=
TOPIC_TUGAS_ID=
TOPIC_JADWAL_ID=
TOPIC_SERVER_ID=
TOPIC_STATUS_ID=
```

> 💡 **Cara Menggunakan Mode Grup Forum (Topics):**
> 1. Buat Grup Telegram, aktifkan fitur **Topics (Forum)** pada pengaturan grup.
> 2. Buat 6 Topik: `Presensi`, `Materi Baru`, `Tugas Baru`, `Jadwal Kuliah`, `Info VM`, dan `Status Kehadiran`.
> 3. Masukkan Bot ke grup dan jadikan sebagai Admin.
> 4. Ketik `/getid` di dalam masing-masing topik untuk mengetahui ID topik tersebut.
> 5. Masukkan ID topik yang didapat ke file `.env`, lalu restart bot (`sudo systemctl restart autoabsen`).
> 6. Ketik `/setup_panels` di Telegram untuk memasang panel tombol otomatis di setiap topik!

### 4. Uji Coba Manual
Jalankan bot secara langsung di terminal untuk memastikan login dan bot Telegram bekerja:
```bash
python3 main.py
```
*Jika berhasil, bot akan mengirimkan pesan pemberitahuan awal ke Telegram kamu.*  
Tekan `Ctrl + C` untuk menghentikan uji coba.

---

## ⚙️ Menjalankan Non-Stop 24/7 (Systemd Service)

Agar bot tetap berjalan di latar belakang meskipun terminal ditutup atau VM baru di-restart:

### 1. Pasang Service File ke Systemd
```bash
sudo cp /home/ary/autoabsen/autoabsen.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### 2. Aktifkan dan Jalankan Service
```bash
# Aktifkan agar otomatis menyala saat VM booting
sudo systemctl enable autoabsen

# Jalankan servicenya sekarang
sudo systemctl start autoabsen
```

### 3. Perintah Berguna untuk Manajemen Service
- **Cek Status Service**:
  ```bash
  sudo systemctl status autoabsen
  ```
- **Melihat Log Realtime**:
  ```bash
  journalctl -u autoabsen -f
  ```
- **Restart Service**:
  ```bash
  sudo systemctl restart autoabsen
  ```
- **Stop Service**:
  ```bash
  sudo systemctl stop autoabsen
  ```

---

## 📱 Format Pesan di Telegram

Saat dosen membuka presensi dan bot berhasil melakukan absen:
```text
🔔 PRESENSI BERHASIL DILAKUKAN!

📚 Matakuliah : Kewirausahaan
👨‍🏫 Dosen      : Dr. Ir. Firman Arifin, ST, MT
🕒 Dibuka Dosen : Jumat, 11 September 2026 - 09:47:33 WIB
🤖 Eksekusi Bot : Jumat, 11 September 2026 - 09:47:45 WIB
✅ Status       : Hadir (Sukses Dicatat)

Presensi otomatis dicatat oleh AutoAbsen Bot.
```
