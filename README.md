# APB-PENS (Auto Presensi Bot - ETHOL PENS)

Bot otomatisasi presensi perkuliahan ETHOL PENS berbasis Python yang terintegrasi langsung dengan Telegram Bot API. Dilengkapi fitur notifikasi tugas & materi baru, pengumpulan tugas via chat Telegram, dan pemantauan status server.

---

## Fitur

- **Autentikasi CAS SSO**: Menangani login SSO PENS otomatis dengan penanganan pembaruan sesi berkala.
- **Presensi Otomatis**: Polling berkala untuk mendeteksi sesi presensi aktif dan melakukan presensi secara otomatis.
- **Notifikasi Tugas & Materi**: Mengirim pemberitahuan ke Telegram saat dosen mengunggah materi atau tugas baru.
- **Pengumpulan Tugas via Telegram**: Alur interaktif pemilihan mata kuliah & judul tugas untuk upload berkas langsung ke ETHOL.
- **Dukungan Telegram Forum (Topics)**: Pemisahan kanal pesan berdasarkan topik (Presensi, Materi, Tugas, Jadwal, Server, Status).
- **Diagnostik Server**: Cek alokasi IP, ping latensi jaringan, penggunaan memori/disk, dan kontrol restart VM.
- **Systemd Service**: Konfigurasi daemon untuk eksekusi latar belakang 24/7 di Ubuntu / Debian.

---

## Persyaratan Sistem

- Python 3.9+
- Linux (Ubuntu/Debian direkomendasikan untuk integrasi systemd)

---

## Instalasi

### 1. Clone & Pasang Dependensi

```bash
git clone https://github.com/UniverseZ07/APB-PENS.git
cd APB-PENS

# Membuat dan mengaktifkan virtualenv
python3 -m venv venv
source venv/bin/activate

# Install dependensi
pip install -r requirements.txt
```

### 2. Konfigurasi Environment

Salin berkas contoh `.env.example` menjadi `.env`:

```bash
cp .env.example .env
```

Sesuaikan nilai variabel di dalam berkas `.env`:

```ini
ETHOL_EMAIL=email_kamu@student.pens.ac.id
ETHOL_PASSWORD=password_sso_kamu
TELEGRAM_BOT_TOKEN=token_bot_telegram
TELEGRAM_CHAT_ID=chat_id_atau_group_id
CHECK_INTERVAL_SECONDS=30
TIMEZONE=Asia/Jakarta

# Opsional: ID Topik jika menggunakan Telegram Supergroup Forum
TOPIC_PRESENSI_ID=
TOPIC_MATERI_ID=
TOPIC_TUGAS_ID=
TOPIC_JADWAL_ID=
TOPIC_SERVER_ID=
TOPIC_STATUS_ID=
```

---

## Menjalankan Bot

### Mode Manual (Pengujian)

```bash
python3 main.py
```

### Mode Service (Systemd / Background 24/7)

1. Salin unit file service ke direktori systemd:
   ```bash
   sudo cp autoabsen.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

2. Aktifkan dan jalankan service:
   ```bash
   sudo systemctl enable autoabsen
   sudo systemctl start autoabsen
   ```

3. Perintah manajemen service:
   ```bash
   # Cek status
   sudo systemctl status autoabsen

   # Monitoring log
   journalctl -u autoabsen -f

   # Restart service
   sudo systemctl restart autoabsen
   ```

---

## Perintah Bot di Telegram

| Perintah | Fungsi |
|---|---|
| `/menu` | Menampilkan menu navigasi utama |
| `/status` | Menampilkan informasi akun, persentase kehadiran, dan koneksi ETHOL |
| `/tugas` | Menampilkan daftar tugas kuliah aktif yang belum dikumpulkan |
| `/kumpul` | Memulai alur pengumpulan tugas langsung ke ETHOL |
| `/server` | Menampilkan diagnostik IP, latensi jaringan, dan utilisasi RAM |
| `/getid` | Menampilkan Chat ID dan Thread/Topic ID saat ini |
| `/setup_panels` | Memasang panel interaktif di tiap topik forum |

---

## Struktur Berkas

```text
├── .env.example          # Template konfigurasi environment
├── .gitignore            # Filter berkas sensitif dan temporary
├── autoabsen.service     # Unit file systemd
├── ethol_client.py       # API client & autentikasi SSO ETHOL
├── main.py               # Entrypoint & loop polling presensi/notifikasi
├── requirements.txt      # Daftar dependensi Python
├── system_diagnostic.py  # Modul diagnostik sistem dan jaringan
└── telegram_notifier.py  # Wrapper integrasi Telegram Bot API
```
