import logging
import html
from typing import Optional, Dict, Any, List, Tuple
import requests

logger = logging.getLogger("telegram_notifier")


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        topic_presensi_id: Optional[int] = None,
        topic_materi_id: Optional[int] = None,
        topic_tugas_id: Optional[int] = None,
        topic_jadwal_id: Optional[int] = None,
        topic_server_id: Optional[int] = None,
        topic_status_id: Optional[int] = None,
        topic_general_id: Optional[int] = None
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.topic_presensi_id = topic_presensi_id
        self.topic_materi_id = topic_materi_id
        self.topic_tugas_id = topic_tugas_id
        self.topic_jadwal_id = topic_jadwal_id
        self.topic_server_id = topic_server_id
        self.topic_status_id = topic_status_id
        self.topic_general_id = topic_general_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.file_base_url = f"https://api.telegram.org/file/bot{self.bot_token}"

    def set_bot_commands(self) -> bool:
        """Mendaftarkan menu tombol perintah [/] di aplikasi Telegram."""
        try:
            url = f"{self.base_url}/setMyCommands"
            commands = [
                {"command": "status", "description": "📊 Status Kehadiran & Akun"},
                {"command": "jadwal", "description": "📅 Jadwal Kuliah Hari Ini & Semester"},
                {"command": "materi", "description": "📚 Unduh & Buka Materi Kuliah"},
                {"command": "tugas", "description": "📝 Daftar Tugas Kuliah"},
                {"command": "kumpul", "description": "📤 Kumpulkan Tugas Kuliah"},
                {"command": "server", "description": "🖥️ Info VM, IP, RAM & Koneksi"},
                {"command": "getid", "description": "🆔 Cek ID Chat & ID Topik Forum"},
                {"command": "setup_panels", "description": "🚀 Pasang Panel Menu di Semua Topik"},
                {"command": "menu", "description": "📱 Menu Navigasi Utama"}
            ]
            res = requests.post(url, json={"commands": commands}, timeout=10)
            if res.status_code == 200 and res.json().get("ok"):
                logger.info("Berhasil mendaftarkan bot commands di Telegram.")
                return True
            logger.warning("Gagal mendaftarkan bot commands: %s", res.text)
            return False
        except Exception as e:
            logger.error("Exception set_bot_commands: %s", e)
            return False

    def get_default_keyboard(self) -> Dict[str, Any]:
        """Menghasilkan keyboard tombol cepat di layar Telegram."""
        return {
            "keyboard": [
                [{"text": "📊 Status"}, {"text": "📅 Jadwal Kuliah"}],
                [{"text": "📝 Daftar Tugas"}, {"text": "📤 Kumpulkan Tugas"}],
                [{"text": "🖥️ Info Server & VM"}]
            ],
            "resize_keyboard": True,
            "persistent": True
        }

    def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        with_keyboard: bool = False,
        reply_markup: Optional[Dict[str, Any]] = None,
        message_thread_id: Optional[int] = None,
        chat_id: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Mengirim pesan ke chat Telegram (mendukung forum topic / message_thread_id)."""
        try:
            url = f"{self.base_url}/sendMessage"
            target_chat = chat_id or self.chat_id
            payload = {
                "chat_id": target_chat,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            if message_thread_id is not None:
                payload["message_thread_id"] = message_thread_id

            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            elif with_keyboard:
                payload["reply_markup"] = self.get_default_keyboard()

            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200 and res.json().get("ok"):
                return res.json().get("result")
            logger.error("Gagal kirim pesan Telegram: %s", res.text)
            return None
        except Exception as e:
            logger.error("Exception kirim pesan Telegram: %s", e)
            return None

    def send_message_to_general(
        self,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Mengirim pesan ke topik General (Forum Topic 1 atau Non-topic fallback).
        Mencoba dengan topic_general_id terlebih dahulu, dan fallback tanpa thread ID jika tidak ditemukan.
        """
        target_thread = self.topic_general_id
        res = self.send_message(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            message_thread_id=target_thread
        )
        if res is None and target_thread is not None:
            logger.info("Gagal kirim ke topic_general_id %s, mencoba fallback tanpa message_thread_id...", target_thread)
            res = self.send_message(
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                message_thread_id=None
            )
        return res

    def edit_message_text(
        self,
        chat_id: Any,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Mengedit pesan teks yang sudah ada (misalnya saat navigasi tombol inline)."""
        try:
            url = f"{self.base_url}/editMessageText"
            payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup

            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200 and res.json().get("ok"):
                return True
            if "message is not modified" in res.text:
                return True
            logger.warning("Gagal edit pesan Telegram: %s", res.text)
            return False
        except Exception as e:
            logger.error("Exception edit_message_text: %s", e)
            return False

    def edit_message_reply_markup(
        self,
        chat_id: Any,
        message_id: int,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Mengedit atau menghapus keyboard inline pada pesan tertentu (misal menghapus tombol batalkan saat file diupload)."""
        try:
            url = f"{self.base_url}/editMessageReplyMarkup"
            payload = {
                "chat_id": chat_id,
                "message_id": message_id,
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            else:
                payload["reply_markup"] = {"inline_keyboard": []}

            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200 and res.json().get("ok"):
                return True
            if "message is not modified" in res.text:
                return True
            return False
        except Exception as e:
            logger.error("Exception edit_message_reply_markup: %s", e)
            return False

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> bool:
        """Memberi respon pada callback query agar animasi loading di tombol hilang."""
        try:
            url = f"{self.base_url}/answerCallbackQuery"
            payload = {"callback_query_id": callback_query_id}
            if text:
                payload["text"] = text
            res = requests.post(url, json=payload, timeout=10)
            return res.status_code == 200 and res.json().get("ok", False)
        except Exception as e:
            logger.error("Exception answer_callback_query: %s", e)
            return False

    def download_telegram_file(self, file_id: str) -> Optional[Tuple[str, bytes]]:
        """
        Mengunduh file yang dikirimkan pengguna dari server Telegram.
        Mengembalikan (file_path_name, file_bytes).
        """
        try:
            get_file_url = f"{self.base_url}/getFile"
            res = requests.get(get_file_url, params={"file_id": file_id}, timeout=15)
            if res.status_code != 200 or not res.json().get("ok"):
                logger.error("Gagal getFile Telegram: %s", res.text)
                return None

            file_path = res.json()["result"]["file_path"]
            download_url = f"{self.file_base_url}/{file_path}"
            
            logger.info("Mengunduh file dari %s...", download_url)
            file_res = requests.get(download_url, timeout=60)
            if file_res.status_code == 200:
                file_name = file_path.split("/")[-1]
                return file_name, file_res.content
            logger.error("Gagal unduh konten file: HTTP %s", file_res.status_code)
            return None
        except Exception as e:
            logger.exception("Exception download_telegram_file: %s", e)
            return None

    def notify_presensi_success(
        self,
        matakuliah: str,
        dosen: str,
        waktu_buka: str,
        waktu_absen: str,
        status: str = "Hadir (Sukses Dicatat)"
    ) -> Optional[Dict[str, Any]]:
        """Mengirim notifikasi presensi berhasil dilakukan ke topik Presensi."""
        message = (
            "🔔 <b>PRESENSI BERHASIL DILAKUKAN!</b>\n\n"
            f"📚 <b>Matakuliah</b> : {html.escape(str(matakuliah))}\n"
            f"👨‍🏫 <b>Dosen</b>      : {html.escape(str(dosen))}\n"
            f"🕒 <b>Dibuka Dosen</b> : {html.escape(str(waktu_buka))}\n"
            f"🤖 <b>Eksekusi Bot</b> : {html.escape(str(waktu_absen))}\n"
            f"✅ <b>Status</b>       : <b>{html.escape(str(status))}</b>\n\n"
            "<i>Presensi otomatis dicatat oleh AutoAbsen Bot.</i>"
        )
        return self.send_message(message, message_thread_id=self.topic_presensi_id)

    def notify_presensi_failed(
        self,
        matakuliah: str,
        dosen: str,
        waktu_buka: str,
        pesan_gagal: str
    ) -> Optional[Dict[str, Any]]:
        """Mengirim peringatan jika presensi gagal dieksekusi ke topik Presensi."""
        message = (
            "⚠️ <b>PERINGATAN: PRESENSI GAGAL DIEKSEKUSI!</b>\n\n"
            f"📚 <b>Matakuliah</b> : {html.escape(str(matakuliah))}\n"
            f"👨‍🏫 <b>Dosen</b>      : {html.escape(str(dosen))}\n"
            f"🕒 <b>Dibuka Dosen</b> : {html.escape(str(waktu_buka))}\n"
            f"❌ <b>Penyebab</b>     : {html.escape(str(pesan_gagal))}\n\n"
            "⚠️ <i>Segera lakukan presensi manual melalui web ETHOL!</i>"
        )
        return self.send_message(message, message_thread_id=self.topic_presensi_id)

    def notify_new_task(
        self,
        matakuliah: str,
        judul: str,
        waktu_upload: str
    ) -> Optional[Dict[str, Any]]:
        """Mengirim notifikasi otomatis saat dosen mengunggah tugas baru ke topik Tugas."""
        message = (
            "📝 <b>NOTIFIKASI TUGAS BARU!</b>\n\n"
            f"📚 <b>Matakuliah</b>   : {html.escape(str(matakuliah))}\n"
            f"📌 <b>Judul Tugas</b>  : {html.escape(str(judul))}\n"
            f"🕒 <b>Waktu Dibuat</b> : {html.escape(str(waktu_upload))}\n\n"
            "💡 <i>Gunakan tombol di bawah untuk melihat detail atau mengumpulkan file tugas.</i>"
        )
        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📝 Lihat Daftar Tugas", "callback_data": "task_page_0"},
                    {"text": "📤 Kumpulkan Tugas", "callback_data": "kumpul_menu"}
                ]
            ]
        }
        return self.send_message(message, reply_markup=inline_keyboard, message_thread_id=self.topic_tugas_id)

    def send_document(
        self,
        document: Tuple[str, bytes],
        caption: Optional[str] = None,
        parse_mode: str = "HTML",
        message_thread_id: Optional[int] = None,
        chat_id: Optional[Any] = None,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Mengirim dokumen/file ke chat Telegram (mendukung topik forum)."""
        try:
            url = f"{self.base_url}/sendDocument"
            target_chat = chat_id or self.chat_id
            data: Dict[str, Any] = {"chat_id": str(target_chat)}
            if message_thread_id is not None:
                data["message_thread_id"] = str(message_thread_id)
            if caption:
                data["caption"] = caption
                data["parse_mode"] = parse_mode
            if reply_markup:
                import json
                data["reply_markup"] = json.dumps(reply_markup)

            file_name, file_bytes = document
            files = {
                "document": (file_name, file_bytes)
            }
            res = requests.post(url, data=data, files=files, timeout=60)
            if res.status_code == 200 and res.json().get("ok"):
                return res.json().get("result")
            logger.error("Gagal kirim dokumen Telegram: %s", res.text)
            return None
        except Exception as e:
            logger.exception("Exception send_document Telegram: %s", e)
            return None

    def notify_new_material(
        self,
        matakuliah: str,
        judul: str,
        waktu_upload: str,
        kuliah_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Mengirim notifikasi otomatis saat dosen mengunggah materi baru ke topik Materi."""
        message = (
            "📖 <b>NOTIFIKASI MATERI BARU!</b>\n\n"
            f"📚 <b>Matakuliah</b>     : {html.escape(str(matakuliah))}\n"
            f"📑 <b>Judul Materi</b>   : {html.escape(str(judul))}\n"
            f"🕒 <b>Waktu Diunggah</b> : {html.escape(str(waktu_upload))}\n\n"
            "💡 <i>Materi perkuliahan baru telah diunggah oleh Dosen di website ETHOL.</i>"
        )
        inline_keyboard = None
        if kuliah_id is not None:
            inline_keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "📥 Unduh / Buka Materi", "callback_data": f"materi_course_{kuliah_id}"},
                        {"text": "📚 Semua Materi", "callback_data": "materi_menu"}
                    ]
                ]
            }
        return self.send_message(
            message,
            reply_markup=inline_keyboard,
            message_thread_id=self.topic_materi_id
        )

    def notify_bot_started(self, nama: str, nrp: str, check_interval: int) -> Optional[Dict[str, Any]]:
        """Mengirim pemberitahuan saat bot pertama kali dijalankan."""
        message = (
            "🚀 <b>AutoAbsen ETHOL Bot Aktif!</b>\n\n"
            f"👤 <b>Akun</b>     : {html.escape(str(nama))} (NRP: {html.escape(str(nrp))})\n"
            f"⏱️ <b>Interval</b> : Setiap {check_interval} detik\n"
            "🟢 <b>Status</b>   : Siaga memantau presensi dosen secara otomatis\n\n"
            "Pilih menu di bawah atau kunjungi topik yang tersedia untuk berinteraksi."
        )
        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📊 Status & Kehadiran", "callback_data": "menu_status"},
                    {"text": "📅 Jadwal Kuliah", "callback_data": "jadwal_today"}
                ],
                [
                    {"text": "📝 Daftar Tugas", "callback_data": "task_page_0"},
                    {"text": "📤 Kumpulkan Tugas", "callback_data": "kumpul_menu"}
                ],
                [
                    {"text": "🖥️ Info VM & Server", "callback_data": "server_info"}
                ]
            ]
        }
        # Kirim ke topik status jika ada, atau ke chat_id utama
        target_thread = self.topic_status_id or self.topic_presensi_id
        return self.send_message(message, reply_markup=inline_keyboard, message_thread_id=target_thread)

    def notify_ethol_down(
        self,
        alasan: str,
        waktu: str
    ) -> Optional[Dict[str, Any]]:
        """Mengirim notifikasi ke topik General bahwa server ETHOL sedang tidak bisa diakses / down."""
        lines = [
            "🚨 <b>PERINGATAN: SERVER ETHOL TIDAK DAPAT DIAKSES!</b>",
            "",
            "🔴 <b>Status</b> : <b>Down / Gangguan Akses</b>",
            f"🕒 <b>Waktu Terdeteksi</b> : {html.escape(str(waktu))}",
            "⚠️ <b>Penyebab / Detail Masalah</b> :",
            f"<code>{html.escape(str(alasan))}</code>",
            "",
            "🤖 <i>Bot AutoAbsen akan terus memantau di latar belakang dan otomatis memberi tahu di topik ini saat server ETHOL kembali normal.</i>"
        ]
        message = "\n".join(lines)
        return self.send_message_to_general(message)

    def notify_ethol_recovered(
        self,
        waktu: str,
        durasi: Optional[str] = None,
        nama: Optional[str] = None,
        nrp: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Mengirim notifikasi ke topik General bahwa server ETHOL sudah pulih dan dapat diakses kembali."""
        lines = [
            "✅ <b>PEMBERITAHUAN: SERVER ETHOL KEMBALI NORMAL!</b>",
            "",
            "🟢 <b>Status</b> : <b>Sudah Dapat Diakses Kembali</b>",
            f"🕒 <b>Waktu Pulih</b> : {html.escape(str(waktu))}",
        ]
        if durasi:
            lines.append(f"⏱️ <b>Durasi Gangguan</b> : {html.escape(str(durasi))}")
        if nama and nrp:
            lines.append(f"👤 <b>Akun Terhubung</b> : {html.escape(str(nama))} (NRP: {html.escape(str(nrp))})")
        lines.extend([
            "",
            "🚀 <i>Sesi login berhasil diperbarui. Pemantauan presensi dan notifikasi kembali berjalan normal.</i>"
        ])
        message = "\n".join(lines)
        return self.send_message_to_general(message)

    def format_status_text(
        self,
        nama: str,
        nrp: str,
        is_ethol_active: bool,
        total_courses: int,
        rata_hadir: Optional[Any],
        total_sesi: Optional[Any],
        last_check_time: str,
        interval: int,
        total_attended_keys: int
    ) -> str:
        """Membuat teks ringkasan status bot dan kehadiran mahasiswa."""
        rata_hadir_str = f"{rata_hadir}%" if rata_hadir is not None else "100%"
        sesi_str = f" ({total_sesi} sesi dibuka)" if total_sesi is not None else ""
        ethol_status = "🟢 Aktif (Terhubung)" if is_ethol_active else "🔴 Perlu Login Ulang"

        return (
            "📊 <b>STATUS AUTOABSEN ETHOL</b>\n\n"
            f"👤 <b>Mahasiswa</b> : {html.escape(str(nama))}\n"
            f"🆔 <b>NRP</b> : <code>{html.escape(str(nrp))}</code>\n"
            f"📚 <b>Mata Kuliah</b> : {total_courses} Matakuliah semester ini\n"
            f"📈 <b>Rata-rata Kehadiran</b> : <b>{rata_hadir_str}</b>{sesi_str}\n"
            f"🟢 <b>Status ETHOL</b> : {ethol_status}\n"
            f"🕒 <b>Pengecekan Terakhir</b> : {last_check_time}\n"
            f"⏱️ <b>Interval Polling</b> : Setiap {interval} detik\n"
            f"📝 <b>Riwayat Presensi Tersimpan</b> : {total_attended_keys} sesi"
        )

    def format_tasks_by_course(self, tasks: List[Dict[str, Any]], page: int = 0, courses_per_page: int = 2) -> tuple:
        """
        Mengelompokkan tugas per mata kuliah & dosen, lalu membaginya ke dalam beberapa halaman.
        Mengembalikan (text, inline_keyboard, total_pages).
        """
        if not tasks:
            text = (
                "🎉 <b>SEMUA TUGAS BERES!</b>\n\n"
                "Tidak ada tugas kuliah yang belum dikumpulkan saat ini di ETHOL. Mantap! 👍"
            )
            inline_keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "📤 Kumpulkan Tugas", "callback_data": "kumpul_menu"},
                        {"text": "🔄 Segarkan Data", "callback_data": f"task_page_{page}"}
                    ]
                ]
            }
            return text, inline_keyboard, 0

        grouped: Dict[str, Dict[str, Any]] = {}
        for t in tasks:
            mk = t.get("matakuliah") or "Mata Kuliah"
            dosen = t.get("dosen") or "Dosen Pengampu"
            key = f"{mk}___{dosen}"
            if key not in grouped:
                grouped[key] = {
                    "matakuliah": mk,
                    "dosen": dosen,
                    "tasks": []
                }
            grouped[key]["tasks"].append(t)

        group_list = list(grouped.values())
        total_courses_with_tasks = len(group_list)
        total_pages = (total_courses_with_tasks + courses_per_page - 1) // courses_per_page

        if page >= total_pages:
            page = max(0, total_pages - 1)
        if page < 0:
            page = 0

        start_idx = page * courses_per_page
        end_idx = min(start_idx + courses_per_page, total_courses_with_tasks)
        current_groups = group_list[start_idx:end_idx]

        lines = [
            f"📋 <b>DAFTAR TUGAS BELUM DIKUMPULKAN</b>\n"
            f"🗓️ <b>Halaman</b> : {page + 1} / {total_pages}\n"
            f"📌 <i>Total {len(tasks)} tugas pada {total_courses_with_tasks} mata kuliah</i>\n"
        ]

        for g in current_groups:
            mk_name = html.escape(str(g["matakuliah"]))
            dosen_name = html.escape(str(g["dosen"]))
            lines.append(f"📚 <b>{mk_name}</b> (<i>{dosen_name}</i>) :")

            for idx, item in enumerate(g["tasks"], 1):
                judul = html.escape(str(item.get("judul", "Tugas")))
                deadline = html.escape(str(item.get("deadline", "Tidak ditentukan")))
                is_open = item.get("tutup") == 0
                status_str = "🟢 Masih Dibuka" if is_open else "🔴 Sudah Ditutup Dosen"

                lines.append(
                    f"  <b>• {judul}</b>\n"
                    f"    ⏰ Tenggat : <code>{deadline}</code>\n"
                    f"    📌 Status : {status_str}"
                )
            lines.append("")

        lines.append("💡 <i>Kamu juga bisa kumpulkan tugas langsung via bot!</i>")
        text = "\n".join(lines)

        nav_buttons = []
        if page > 0:
            nav_buttons.append({"text": "⬅️ Prev", "callback_data": f"task_page_{page - 1}"})
        if page < total_pages - 1:
            nav_buttons.append({"text": "➡️ Next", "callback_data": f"task_page_{page + 1}"})

        keyboard_rows = []
        if nav_buttons:
            keyboard_rows.append(nav_buttons)

        keyboard_rows.append([
            {"text": "📤 Kumpulkan Tugas", "callback_data": "kumpul_menu"},
            {"text": "🔄 Segarkan", "callback_data": f"task_page_{page}"}
        ])

        inline_keyboard = {"inline_keyboard": keyboard_rows}
        return text, inline_keyboard, total_pages

    def format_courses_for_submission(self, courses: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """Menghasilkan menu pemilihan mata kuliah untuk pengumpulan tugas."""
        text = (
            "📤 <b>PENGUMPULAN TUGAS KE ETHOL</b>\n\n"
            "Pilih mata kuliah yang ingin kamu kumpulkan tugasnya:"
        )
        buttons = []
        for c in courses:
            kid = c.get("nomor")
            mk_name = (
                c.get("matakuliah", {}).get("nama")
                or c.get("nama")
                or f"Matakuliah #{kid}"
            )
            buttons.append([
                {"text": f"📚 {mk_name}", "callback_data": f"kumpul_course_{kid}"}
            ])

        buttons.append([
            {"text": "📋 Lihat Tugas Belum Dikumpul", "callback_data": "task_page_0"}
        ])

        return text, {"inline_keyboard": buttons}

    def format_tasks_for_submission(self, course_name: str, tasks: List[Dict[str, Any]], kuliah_id: int) -> Tuple[str, Dict[str, Any]]:
        """Menghasilkan menu pemilihan tugas dalam suatu mata kuliah."""
        if not tasks:
            text = (
                f"📚 <b>{html.escape(course_name)}</b>\n\n"
                "ℹ️ Tidak ditemukan tugas untuk mata kuliah ini di ETHOL."
            )
            buttons = [
                [{"text": "⬅️ Pilih Mata Kuliah Lain", "callback_data": "kumpul_menu"}]
            ]
            return text, {"inline_keyboard": buttons}

        text = (
            f"📚 <b>Matakuliah</b> : <b>{html.escape(course_name)}</b>\n\n"
            "Pilih judul tugas yang ingin kamu kumpulkan / ubah:"
        )
        buttons = []
        for t in tasks:
            tid = t.get("nomor") or t.get("id") or t.get("id_tugas")
            judul = t.get("judul") or t.get("title") or "Tugas"
            is_submitted = bool(t.get("nomor_tugas_mahasiswa") or t.get("submission_time"))
            is_open = t.get("tutup") == 0

            if is_submitted:
                btn_title = f"📝 {judul[:26]} (Ubah File)"
            elif is_open:
                btn_title = f"🟢 {judul[:26]} (Kumpulkan)"
            else:
                btn_title = f"🔴 {judul[:26]} (Ditutup)"

            buttons.append([
                {"text": btn_title, "callback_data": f"kumpul_task_{kuliah_id}_{tid}"}
            ])

        buttons.append([
            {"text": "⬅️ Pilih Mata Kuliah Lain", "callback_data": "kumpul_menu"},
            {"text": "❌ Batalkan", "callback_data": "kumpul_cancel"}
        ])

        return text, {"inline_keyboard": buttons}

    def format_waiting_file_prompt(
        self,
        course_name: str,
        task_title: str,
        deadline: str,
        is_submitted: bool = False,
        is_closed: bool = False,
        prev_file_name: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Menghasilkan pesan konfirmasi menunggu pengiriman file tugas."""
        if is_submitted:
            header = "📤 <b>UBAH / PERBARUI FILE TUGAS</b>"
            status_str = "📝 Sudah Pernah Dikumpulkan (Opsi: Ganti File)"
            action_desc = (
                "📎 <b>Silakan KIRIM FILE BARU (PDF, DOCX, ZIP, dsb.) ke chat ini.</b>\n\n"
                "💡 <i>File baru akan secara otomatis <b>MENGGANTIKAN (REPLACE)</b> file tugas sebelumnya di ETHOL tanpa membuat duplikat tugas baru.</i>"
            )
        else:
            header = "📤 <b>PENGUMPULAN TUGAS BARU</b>"
            status_str = "🔴 Sudah Ditutup Dosen" if is_closed else "🟢 Belum Dikumpulkan"
            action_desc = (
                "📎 <b>Silakan KIRIM FILE tugas kamu (PDF, DOCX, ZIP, dsb.) langsung ke chat ini.</b>\n\n"
                "<i>Bot akan mengunggah file tersebut langsung ke ETHOL atas nama akunmu.</i>"
            )

        text = (
            f"{header}\n\n"
            f"📚 <b>Matakuliah</b> : {html.escape(str(course_name))}\n"
            f"📝 <b>Judul Tugas</b> : <b>{html.escape(str(task_title))}</b>\n"
            f"⏰ <b>Tenggat</b>     : <code>{html.escape(str(deadline))}</code>\n"
            f"📌 <b>Status</b>     : {status_str}\n\n"
            f"{action_desc}"
        )
        buttons = [
            [{"text": "❌ Batalkan Pengumpulan", "callback_data": "kumpul_cancel"}]
        ]
        return text, {"inline_keyboard": buttons}

    def notify_task_submit_success(
        self,
        course_name: str,
        task_title: str,
        file_name: str,
        file_size_kb: float,
        upload_time: str,
        is_update: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Mengirim laporan sukses pengumpulan atau pembaruan tugas ke topik Tugas."""
        header = "✅ <b>FILE TUGAS BERHASIL DIPERBARUI DI ETHOL!</b>" if is_update else "✅ <b>TUGAS BERHASIL DIKUMPULKAN KE ETHOL!</b>"
        status_note = "File lama berhasil digantikan dengan file terbaru (tidak ada duplikat)" if is_update else "Tersimpan di Server ETHOL"

        message = (
            f"{header}\n\n"
            f"📚 <b>Matakuliah</b>   : {html.escape(str(course_name))}\n"
            f"📝 <b>Judul Tugas</b>  : {html.escape(str(task_title))}\n"
            f"📁 <b>File Terunggah</b>: <code>{html.escape(str(file_name))}</code> ({file_size_kb:.1f} KB)\n"
            f"🕒 <b>Waktu Submit</b> : {html.escape(str(upload_time))}\n"
            f"🟢 <b>Status</b>       : <b>{html.escape(status_note)}</b>\n\n"
            "<i>Kamu bisa memeriksa status pengumpulan kapan saja di web ETHOL atau via bot.</i>"
        )
        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📝 Cek Daftar Tugas", "callback_data": "task_page_0"},
                    {"text": "📤 Kumpulkan Tugas Lain", "callback_data": "kumpul_menu"}
                ]
            ]
        }
        return self.send_message(message, reply_markup=inline_keyboard, message_thread_id=self.topic_tugas_id)

    def notify_task_submit_failed(
        self,
        course_name: str,
        task_title: str,
        file_name: str,
        error_msg: str
    ) -> Optional[Dict[str, Any]]:
        """Mengirim laporan gagal pengumpulan tugas ke topik Tugas."""
        message = (
            "❌ <b>GAGAL MENGUMPULKAN TUGAS KE ETHOL!</b>\n\n"
            f"📚 <b>Matakuliah</b> : {html.escape(str(course_name))}\n"
            f"📝 <b>Judul Tugas</b> : {html.escape(str(task_title))}\n"
            f"📁 <b>File</b>        : <code>{html.escape(str(file_name))}</code>\n"
            f"⚠️ <b>Penyebab</b>    : {html.escape(str(error_msg))}\n\n"
            "<i>Silakan coba kirim ulang file atau kumpulkan langsung via web ETHOL jika mendesak.</i>"
        )
        inline_keyboard = {
            "inline_keyboard": [
                [{"text": "🔄 Coba Kumpulkan Lagi", "callback_data": "kumpul_menu"}]
            ]
        }
        return self.send_message(message, reply_markup=inline_keyboard, message_thread_id=self.topic_tugas_id)

    def format_topic_panel_presensi(
        self,
        nama: str,
        nrp: str,
        total_courses: int,
        total_attended_keys: int
    ) -> Tuple[str, Dict[str, Any]]:
        """Menyusun teks & tombol panel untuk Topik Presensi."""
        text = (
            "🔔 <b>PANEL PRESENSI OTOMATIS ETHOL</b>\n\n"
            f"👤 <b>Mahasiswa</b> : {html.escape(str(nama))} (NRP: <code>{html.escape(str(nrp))}</code>)\n"
            f"📚 <b>Mata Kuliah Terpantau</b> : {total_courses} Matakuliah\n"
            f"📝 <b>Total Presensi Tersimpan</b> : {total_attended_keys} sesi\n"
            "🟢 <b>Status</b> : Bot aktif memantau & otomatis absen begitu dosen membuka presensi.\n\n"
            "<i>Laporan presensi berhasil / gagal akan otomatis dikirimkan ke topik ini.</i>"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "🔄 Cek Sesi Presensi Aktif", "callback_data": "presensi_check_active"},
                    {"text": "📊 Status Kehadiran", "callback_data": "menu_status"}
                ]
            ]
        }
        return text, kb

    def format_topic_panel_materi(self, nama: str, nrp: str) -> Tuple[str, Dict[str, Any]]:
        """Menyusun teks & tombol panel untuk Topik Materi Baru."""
        text = (
            "📚 <b>PANEL MATERI PERKULIAHAN ETHOL</b>\n\n"
            f"👤 <b>Mahasiswa</b> : {html.escape(str(nama))} (NRP: <code>{html.escape(str(nrp))}</code>)\n"
            "🟢 <b>Status</b> : Memantau materi baru dan menyediakan download modul/slide kuliah.\n\n"
            "<i>Klik tombol di bawah untuk melihat dan mendownload materi perkuliahan semester ini:</i>"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "📥 Buka & Unduh Materi Kuliah", "callback_data": "materi_menu"}
                ]
            ]
        }
        return text, kb

    def format_materials_course_list(self, courses: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """Menghasilkan menu pemilihan mata kuliah untuk melihat & mengunduh materi."""
        text = (
            "📚 <b>UNDUH MATERI PERKULIAHAN</b>\n\n"
            "Pilih mata kuliah yang ingin kamu lihat atau unduh materinya:"
        )
        buttons = []
        for c in courses:
            kid = c.get("nomor")
            mk_name = (
                c.get("matakuliah", {}).get("nama")
                or c.get("nama")
                or f"Matakuliah #{kid}"
            )
            buttons.append([
                {"text": f"📚 {mk_name}", "callback_data": f"materi_course_{kid}"}
            ])
        buttons.append([
            {"text": "🔄 Segarkan Daftar", "callback_data": "materi_menu"}
        ])
        return text, {"inline_keyboard": buttons}

    def format_course_materials(
        self,
        course_name: str,
        materials: List[Dict[str, Any]],
        kuliah_id: int
    ) -> Tuple[str, Dict[str, Any]]:
        """Menyusun daftar materi perkuliahan untuk suatu matakuliah beserta tombol unduh."""
        lines = [
            f"📚 <b>MATERI: {html.escape(str(course_name))}</b>\n",
            f"📌 <i>Terdapat {len(materials)} materi yang telah diunggah dosen:</i>\n"
        ]

        if not materials:
            lines.append("ℹ️ <i>Belum ada materi atau slide perkuliahan yang diunggah oleh dosen untuk mata kuliah ini.</i>")
            buttons = [
                [{"text": "🔙 Pilih Matakuliah Lain", "callback_data": "materi_menu"}]
            ]
            return "\n".join(lines), {"inline_keyboard": buttons}

        buttons = []
        for idx, item in enumerate(materials, 1):
            mid = item.get("id")
            title = item.get("title") or item.get("judul") or f"Materi #{idx}"
            upload_date = item.get("created_indonesia") or item.get("created") or "-"
            tipe = item.get("tipe", 1)  # 1: file, 2: link
            tipe_label = "🔗 Link Eksternal" if tipe == 2 else "📄 Dokumen / Slide"

            lines.append(
                f"<b>{idx}. {html.escape(str(title))}</b>\n"
                f"   🏷️ Tipe : {tipe_label}\n"
                f"   🕒 Diunggah : {html.escape(str(upload_date))}\n"
            )

            # Tombol download per materi (maksimal 2 tombol per baris jika nama pendek atau 1 tombol)
            btn_label = f"📥 Unduh: {title}"
            if len(btn_label) > 35:
                btn_label = btn_label[:32] + "..."
            buttons.append([
                {"text": btn_label, "callback_data": f"materi_dl_{mid}_{kuliah_id}"}
            ])

        lines.append("💡 <i>Klik tombol materi di bawah untuk langsung mengunduh file ke Telegram.</i>")
        text = "\n".join(lines)

        buttons.append([
            {"text": "🔙 Pilih Matakuliah Lain", "callback_data": "materi_menu"}
        ])

        return text, {"inline_keyboard": buttons}

    def format_topic_panel_tugas(self, nama: str, nrp: str, pending_count: int = 0) -> Tuple[str, Dict[str, Any]]:
        """Menyusun teks & tombol panel untuk Topik Tugas Baru & Kumpul Tugas."""
        status_tugas = f"Terdapat <b>{pending_count} tugas</b> belum dikumpulkan" if pending_count > 0 else "Semua tugas sudah dikumpulkan! 🎉"
        text = (
            "📝 <b>PANEL TUGAS KULIAH & PENGUMPULAN</b>\n\n"
            f"👤 <b>Mahasiswa</b> : {html.escape(str(nama))} (NRP: <code>{html.escape(str(nrp))}</code>)\n"
            f"📌 <b>Status</b> : {status_tugas}\n\n"
            "Kamu bisa mengecek seluruh tugas yang belum dikumpulkan atau mengumpulkan file tugas langsung dari topik ini."
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "📋 Lihat Tugas Belum Dikumpul", "callback_data": "task_page_0"},
                    {"text": "📤 Kumpulkan Tugas Sekarang", "callback_data": "kumpul_menu"}
                ]
            ]
        }
        return text, kb

    def format_topic_panel_jadwal(self, nama: str, nrp: str) -> Tuple[str, Dict[str, Any]]:
        """Menyusun teks & tombol panel untuk Topik Jadwal Kuliah."""
        text = (
            "📅 <b>PANEL JADWAL PERKULIAHAN</b>\n\n"
            f"👤 <b>Mahasiswa</b> : {html.escape(str(nama))} (NRP: <code>{html.escape(str(nrp))}</code>)\n"
            "⏰ <b>Briefing Pagi</b> : Otomatis dikirim setiap pukul 06:00 WIB ke topik ini.\n\n"
            "Gunakan tombol di bawah untuk melihat jadwal perkuliahan hari ini atau seluruh semester:"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "📅 Jadwal Hari Ini", "callback_data": "jadwal_today"},
                    {"text": "🗓️ Semua Jadwal Semester", "callback_data": "jadwal_all"}
                ]
            ]
        }
        return text, kb

    def format_topic_panel_server(self) -> Tuple[str, Dict[str, Any]]:
        """Menyusun teks & tombol panel untuk Topik Info & Kontrol VM."""
        text = (
            "🖥️ <b>PANEL MONITORING & KONTROL SERVER VM</b>\n\n"
            "Topik ini digunakan untuk memantau performa VM Ubuntu (Proxmox), alamat IP jaringan, tes ping latensi internet, dan reboot server dari jarak jauh."
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "📊 Cek Diagnostik & IP Server", "callback_data": "server_info"},
                    {"text": "🔴 Reboot / Restart VM", "callback_data": "server_reboot_confirm"}
                ]
            ]
        }
        return text, kb

    def format_topic_panel_status(
        self,
        nama: str,
        nrp: str,
        total_courses: int,
        rata_hadir: Optional[Any],
        is_ethol_active: bool,
        last_check_time: str
    ) -> Tuple[str, Dict[str, Any]]:
        """Menyusun teks & tombol panel untuk Topik Status Kehadiran."""
        rata_hadir_str = f"{rata_hadir}%" if rata_hadir is not None else "100%"
        ethol_status = "🟢 Aktif (Terhubung)" if is_ethol_active else "🔴 Perlu Login Ulang"
        text = (
            "📊 <b>PANEL STATUS KEHADIRAN & AKUN</b>\n\n"
            f"👤 <b>Mahasiswa</b> : {html.escape(str(nama))}\n"
            f"🆔 <b>NRP</b> : <code>{html.escape(str(nrp))}</code>\n"
            f"📚 <b>Mata Kuliah</b> : {total_courses} Matakuliah semester ini\n"
            f"📈 <b>Rata-rata Kehadiran</b> : <b>{rata_hadir_str}</b>\n"
            f"🟢 <b>Status ETHOL</b> : {ethol_status}\n"
            f"🕒 <b>Pengecekan Terakhir</b> : {last_check_time}"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "🔄 Segarkan Kehadiran", "callback_data": "menu_status"}
                ]
            ]
        }
        return text, kb

    def format_server_info(
        self,
        interfaces: List[Dict[str, Any]],
        connections: List[Dict[str, Any]],
        resources: Dict[str, Any],
        current_time: str
    ) -> Tuple[str, Dict[str, Any]]:
        """Membuat tampilan informasi jaringan, ping test, dan status resource VM."""
        lines = [
            "🖥️ <b>INFORMASI SERVER & JARINGAN UBUNTU VM</b>\n",
            "🌐 <b>Daftar IP Interface VM:</b>"
        ]

        if not interfaces:
            lines.append("  <i>Tidak dapat membaca interface jaringan.</i>")
        else:
            for iface in interfaces:
                name = html.escape(str(iface["name"]))
                status = html.escape(str(iface["status"]))
                ips = iface.get("ips", [])
                if ips:
                    ip_str = ", ".join(f"<code>{ip}</code>" for ip in ips)
                else:
                    ip_str = "<i>(Tidak ada IPv4)</i>"
                status_icon = "🟢" if status.upper() in ["UP", "ACTIVE"] else "⚪"
                lines.append(f"• {status_icon} <b>{name}</b> ({status}) : {ip_str}")

        lines.append("\n📡 <b>Uji Konektivitas Internet & Gateway:</b>")
        if not connections:
            lines.append("  <i>Gagal menjalankan uji konektivitas.</i>")
        else:
            for conn in connections:
                c_name = html.escape(str(conn["name"]))
                c_status = html.escape(str(conn["status"]))
                c_lat = html.escape(str(conn["latency"]))
                lines.append(f"• <b>{c_name}</b> : {c_status} ({c_lat})")

        mem_used = resources.get("mem_used_gb", 0)
        mem_total = resources.get("mem_total_gb", 0)
        mem_percent = resources.get("mem_percent", 0)

        disk_used = resources.get("disk_used_gb", 0)
        disk_total = resources.get("disk_total_gb", 0)
        disk_percent = resources.get("disk_percent", 0)

        uptime = html.escape(str(resources.get("uptime", "-")))

        lines.append("\n📊 <b>Performa & Resource VM:</b>")
        lines.append(f"• 🧠 <b>RAM (Memory)</b> : <b>{mem_used:.2f} GB / {mem_total:.2f} GB ({mem_percent:.1f}%)</b>")
        lines.append(f"• 💾 <b>Penyimpanan Disk</b> : <b>{disk_used:.2f} GB / {disk_total:.2f} GB ({disk_percent:.1f}%)</b>")
        lines.append(f"• ⏱️ <b>Uptime Sistem</b> : {uptime}")
        lines.append(f"• 🕒 <b>Waktu Pengecekan</b> : {current_time}")

        text = "\n".join(lines)

        buttons = [
            [
                {"text": "🔄 Segarkan Info VM", "callback_data": "server_info"},
                {"text": "📡 Test Ping Lagi", "callback_data": "server_ping"}
            ],
            [
                {"text": "⚠️ Restart VM (Reboot)", "callback_data": "server_reboot_confirm"}
            ]
        ]
        return text, {"inline_keyboard": buttons}

    def format_reboot_confirm(self) -> Tuple[str, Dict[str, Any]]:
        """Membuat pesan konfirmasi sebelum melakukan reboot pada VM."""
        text = (
            "⚠️ <b>KONFIRMASI RESTART UBUNTU VM</b>\n\n"
            "Apakah kamu yakin ingin me-restart (reboot) VM sekarang?\n\n"
            "📌 <i>Perhatian:</i>\n"
            "• Seluruh koneksi jaringan & bot akan terputus sementara selama ± 1 menit saat VM reboot.\n"
            "• Bot AutoAbsen akan otomatis menyala kembali setelah VM selesai booting."
        )
        buttons = [
            [
                {"text": "🔴 Ya, Restart VM Sekarang", "callback_data": "server_reboot_execute"},
                {"text": "❌ Batalkan", "callback_data": "server_info"}
            ]
        ]
        return text, {"inline_keyboard": buttons}

    def format_schedule(
        self,
        schedule_items: List[Dict[str, Any]],
        current_time_str: str,
        view_mode: str = "today"
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Menyusun pesan jadwal perkuliahan (Hari Ini / Seluruh Semester) dengan tombol navigasi.
        """
        lines = []
        if view_mode == "today":
            lines.append("📅 <b>JADWAL KULIAH HARI INI</b>")
            lines.append(f"🕒 <i>{current_time_str}</i>\n")
        else:
            lines.append("🗓️ <b>JADWAL KULIAH SEMESTER INI</b>")
            lines.append(f"🕒 <i>{current_time_str}</i>\n")

        if not schedule_items:
            if view_mode == "today":
                lines.append("🎉 <b>Tidak ada jadwal perkuliahan hari ini!</b>")
                lines.append("<i>Selamat beristirahat atau menyelesaikan tugas kuliah.</i>")
            else:
                lines.append("ℹ️ <i>Belum ada jadwal yang tercatat di sistem ETHOL.</i>")
        else:
            for idx, item in enumerate(schedule_items, 1):
                mk = html.escape(str(item.get("matakuliah") or item.get("nama") or f"Matakuliah #{idx}"))
                dosen = html.escape(str(item.get("dosen_lengkap") or item.get("dosen") or item.get("nama_dosen") or "-"))
                hari = html.escape(str(item.get("hari") or item.get("nama_hari") or "-"))
                
                # Format jam/waktu
                jam_awal = item.get("jam_awal")
                jam_akhir = item.get("jam_akhir")
                jam = item.get("jam") or item.get("waktu")
                if not jam and jam_awal and jam_akhir:
                    jam = f"{jam_awal} - {jam_akhir} WIB"
                elif not jam and jam_awal:
                    jam = f"{jam_awal} WIB"
                elif not jam:
                    jam = "-"
                jam_str = html.escape(str(jam))

                ruang = html.escape(str(item.get("ruang") or item.get("nama_ruang") or "Online / Ruang Kelas"))
                kelas = html.escape(str(item.get("kode_kelas") or "-"))
                pararel = html.escape(str(item.get("pararel") or "-"))

                lines.append(f"<b>{idx}. {mk}</b>")
                if view_mode != "today":
                    lines.append(f"   📅 <b>Hari</b> : {hari}")
                if jam_str != "-":
                    lines.append(f"   ⏰ <b>Waktu</b> : <b>{jam_str}</b>")
                lines.append(f"   👨‍🏫 <b>Dosen</b> : {dosen}")
                lines.append(f"   📍 <b>Ruang / Kelas</b> : {ruang} (Kelas: {kelas} {pararel})")
                lines.append("")

        text = "\n".join(lines)

        buttons = []
        if view_mode == "today":
            buttons.append([
                {"text": "🗓️ Lihat Semua Jadwal Semester", "callback_data": "jadwal_all"},
                {"text": "🔄 Segarkan", "callback_data": "jadwal_today"}
            ])
        else:
            buttons.append([
                {"text": "📅 Jadwal Hari Ini Saja", "callback_data": "jadwal_today"},
                {"text": "🔄 Segarkan", "callback_data": "jadwal_all"}
            ])

        return text, {"inline_keyboard": buttons}

    def notify_morning_briefing(
        self,
        schedule_items: List[Dict[str, Any]],
        date_str: str
    ) -> Optional[Dict[str, Any]]:
        """
        Mengirimkan briefing jadwal kuliah pagi hari ke chat Telegram.
        """
        lines = [
            "☀️ <b>SELAMAT PAGI! BRIEFING JADWAL HARI INI</b>",
            f"📅 <b>{date_str}</b>\n"
        ]

        if not schedule_items:
            lines.append("🎉 <b>Tidak ada jadwal perkuliahan hari ini!</b>")
            lines.append("<i>Manfaatkan waktu untuk belajar mandiri atau beristirahat. Semangat!</i>")
        else:
            lines.append(f"Terdapat <b>{len(schedule_items)} mata kuliah</b> yang terjadwal hari ini:\n")
            for idx, item in enumerate(schedule_items, 1):
                mk = html.escape(str(item.get("matakuliah") or item.get("nama") or f"Matakuliah #{idx}"))
                dosen = html.escape(str(item.get("dosen_lengkap") or item.get("dosen") or "-"))
                
                # Format jam/waktu
                jam_awal = item.get("jam_awal")
                jam_akhir = item.get("jam_akhir")
                jam = item.get("jam") or item.get("waktu")
                if not jam and jam_awal and jam_akhir:
                    jam = f"{jam_awal} - {jam_akhir} WIB"
                elif not jam and jam_awal:
                    jam = f"{jam_awal} WIB"
                elif not jam:
                    jam = "Sesuai Jadwal ETHOL"
                jam_str = html.escape(str(jam))

                ruang = html.escape(str(item.get("ruang") or item.get("nama_ruang") or "Online / Lab"))

                lines.append(f"<b>{idx}️⃣ {mk}</b>")
                lines.append(f"   ⏰ <b>Jam</b> : <b>{jam_str}</b>")
                lines.append(f"   👨‍🏫 <b>Dosen</b> : {dosen}")
                lines.append(f"   📍 <b>Ruang</b> : {ruang}")
                lines.append("")

            lines.append("🤖 <i>Bot AutoAbsen tetap siaga memantau & melakukan presensi otomatis begitu dibuka oleh dosen.</i>")

        text = "\n".join(lines)
        kb = {
            "inline_keyboard": [
                [
                    {"text": "📊 Status Presensi", "callback_data": "menu_status"},
                    {"text": "📝 Cek Tugas", "callback_data": "task_page_0"}
                ]
            ]
        }
        return self.send_message(text, reply_markup=kb)

    def get_updates(self, offset: Optional[int] = None, timeout: int = 0) -> List[Dict[str, Any]]:
        """Mengecek pesan masuk / perintah dari pengguna via long-polling ringan."""
        try:
            url = f"{self.base_url}/getUpdates"
            params = {"timeout": timeout}
            if offset is not None:
                params["offset"] = offset
            res = requests.get(url, params=params, timeout=timeout + 5)
            if res.status_code == 200 and res.json().get("ok"):
                return res.json().get("result", [])
            return []
        except Exception:
            return []
