import os
import sys
import time
import json
import re
import html
import signal
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any
from dotenv import load_dotenv

from ethol_client import EtholClient
from telegram_notifier import TelegramNotifier
import system_diagnostic

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("AutoAbsen")

# File penyimpanan riwayat presensi dan notifikasi yang sudah diproses
ATTENDED_FILE = os.path.join(os.path.dirname(__file__), "attended_keys.json")
NOTIFIED_NOTIFS_FILE = os.path.join(os.path.dirname(__file__), "notified_notifs.json")


INDONESIAN_DAYS = {
    "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
    "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
}
INDONESIAN_MONTHS = {
    "January": "Januari", "February": "Februari", "March": "Maret", "April": "April",
    "May": "Mei", "June": "Juni", "July": "Juli", "August": "Agustus",
    "September": "September", "October": "Oktober", "November": "November", "December": "Desember"
}


def format_id_datetime(dt: datetime, with_clock: bool = True) -> str:
    """Memformat objek datetime ke bahasa Indonesia."""
    day_en = dt.strftime("%A")
    month_en = dt.strftime("%B")
    day_id = INDONESIAN_DAYS.get(day_en, day_en)
    month_id = INDONESIAN_MONTHS.get(month_en, month_en)
    if with_clock:
        return f"{day_id}, {dt.day} {month_id} {dt.year} - {dt.strftime('%H:%M:%S')} WIB"
    return f"{day_id}, {dt.day} {month_id} {dt.year}"


def load_attended_keys() -> set:
    if os.path.exists(ATTENDED_FILE):
        try:
            with open(ATTENDED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(str(x) for x in data)
        except Exception as e:
            logger.error("Gagal membaca %s: %s", ATTENDED_FILE, e)
    return set()


def save_attended_keys(keys: set):
    try:
        with open(ATTENDED_FILE, "w", encoding="utf-8") as f:
            json.dump(list(keys), f, indent=2)
    except Exception as e:
        logger.error("Gagal menyimpan %s: %s", ATTENDED_FILE, e)


def load_notified_notifs() -> set:
    if os.path.exists(NOTIFIED_NOTIFS_FILE):
        try:
            with open(NOTIFIED_NOTIFS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(str(x) for x in data)
        except Exception as e:
            logger.error("Gagal membaca %s: %s", NOTIFIED_NOTIFS_FILE, e)
    return set()


def save_notified_notifs(keys: set):
    try:
        with open(NOTIFIED_NOTIFS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(keys), f, indent=2)
    except Exception as e:
        logger.error("Gagal menyimpan %s: %s", NOTIFIED_NOTIFS_FILE, e)


class AutoAbsenApp:
    def __init__(self):
        load_dotenv()

        self.email = os.getenv("ETHOL_EMAIL")
        self.password = os.getenv("ETHOL_PASSWORD")
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "30"))
        self.tz_name = os.getenv("TIMEZONE", "Asia/Jakarta")

        try:
            self.tz = ZoneInfo(self.tz_name)
        except Exception:
            self.tz = ZoneInfo("Asia/Jakarta")

        if not self.email or not self.password:
            logger.critical("ETHOL_EMAIL atau ETHOL_PASSWORD belum dikonfigurasi di file .env!")
            sys.exit(1)

        if not self.bot_token or not self.chat_id:
            logger.critical("TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum dikonfigurasi di file .env!")
            sys.exit(1)

        def parse_topic_id(env_val):
            if env_val is not None and str(env_val).strip() != "":
                clean = str(env_val).strip()
                if clean.isdigit() or (clean.startswith("-") and clean[1:].isdigit()):
                    return int(clean)
            return None

        self.topic_presensi_id = parse_topic_id(os.getenv("TOPIC_PRESENSI_ID"))
        self.topic_materi_id = parse_topic_id(os.getenv("TOPIC_MATERI_ID"))
        self.topic_tugas_id = parse_topic_id(os.getenv("TOPIC_TUGAS_ID"))
        self.topic_jadwal_id = parse_topic_id(os.getenv("TOPIC_JADWAL_ID"))
        self.topic_server_id = parse_topic_id(os.getenv("TOPIC_SERVER_ID"))
        self.topic_status_id = parse_topic_id(os.getenv("TOPIC_STATUS_ID"))

        self.client = EtholClient(email=self.email, password=self.password)
        self.telegram = TelegramNotifier(
            bot_token=self.bot_token,
            chat_id=self.chat_id,
            topic_presensi_id=self.topic_presensi_id,
            topic_materi_id=self.topic_materi_id,
            topic_tugas_id=self.topic_tugas_id,
            topic_jadwal_id=self.topic_jadwal_id,
            topic_server_id=self.topic_server_id,
            topic_status_id=self.topic_status_id
        )
        self.attended_keys = load_attended_keys()
        self.notified_notif_ids = load_notified_notifs()
        self.has_initialized_notifs = os.path.exists(NOTIFIED_NOTIFS_FILE) and len(self.notified_notif_ids) > 0
        self.is_running = True
        self.last_check_time = "Belum pernah"
        self.tele_offset = None
        self.relogin_retry_delay = 30
        self.next_relogin_at = 0.0

        # State session pengumpulan tugas & UI interactivity timeout
        self.active_upload_session: Optional[Dict[str, Any]] = None
        self.active_ui_session: Optional[Dict[str, Any]] = None
        self.ui_timeout_seconds = 180  # 3 menit timeout otomatis untuk mengembalikan ke menu utama default
        self.last_morning_briefing_date: Optional[str] = None

    def get_current_time_str(self) -> str:
        now = datetime.now(self.tz)
        return format_id_datetime(now, with_clock=True)

    def get_student_nrp(self) -> str:
        user = self.client.user_info or {}
        return str(user.get("nipnrp") or user.get("nrp") or "2423600006")

    def get_student_name(self) -> str:
        user = self.client.user_info or {}
        return str(user.get("nama") or "Dary Aulia Fauzan")

    def set_active_ui(self, message_id: Optional[int], chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Mencatat ID pesan aktif, chat_id, thread_id, dan timestamp untuk auto-reset ke tampilan awal topik jika pengguna idle."""
        if message_id:
            self.active_ui_session = {
                "message_id": message_id,
                "chat_id": chat_id or self.chat_id,
                "message_thread_id": message_thread_id,
                "last_activity": time.time()
            }

    def send_or_edit_main_menu(self, message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Menampilkan menu utama navigasi bot atau panel topik default jika dipanggil dari topik spesifik."""
        self.active_ui_session = None
        self.active_upload_session = None
        target_chat = chat_id or self.chat_id

        # Jika dipanggil di dalam topik tertentu, tampilkan panel default topik tersebut
        nama = self.get_student_name()
        nrp = self.get_student_nrp()

        if message_thread_id == self.topic_materi_id and self.topic_materi_id is not None:
            text, menu_kb = self.telegram.format_topic_panel_materi(nama, nrp)
        elif message_thread_id == self.topic_tugas_id and self.topic_tugas_id is not None:
            pending_tasks = self.client.get_pending_tasks()
            text, menu_kb = self.telegram.format_topic_panel_tugas(nama, nrp, pending_count=len(pending_tasks))
        elif message_thread_id == self.topic_jadwal_id and self.topic_jadwal_id is not None:
            text, menu_kb = self.telegram.format_topic_panel_jadwal(nama, nrp)
        elif message_thread_id == self.topic_server_id and self.topic_server_id is not None:
            text, menu_kb = self.telegram.format_topic_panel_server()
        elif message_thread_id == self.topic_status_id and self.topic_status_id is not None:
            courses = self.client.get_enrolled_courses()
            stats = self.client.get_student_stats() or {}
            rata_hadir = stats.get("rataHadir", 100)
            text, menu_kb = self.telegram.format_topic_panel_status(
                nama, nrp, len(courses), rata_hadir, self.client.is_logged_in(), self.last_check_time
            )
        elif message_thread_id == self.topic_presensi_id and self.topic_presensi_id is not None:
            courses = self.client.get_enrolled_courses()
            text, menu_kb = self.telegram.format_topic_panel_presensi(nama, nrp, len(courses), len(self.attended_keys))
        else:
            text = (
                "🤖 <b>AutoAbsen ETHOL Bot Siaga!</b>\n\n"
                "Bot ini berjalan 24/7 di latar belakang untuk:\n"
                "• Melakukan presensi perkuliahan secara otomatis begitu dibuka dosen\n"
                "• Mengirim notifikasi jika ada tugas baru atau materi baru\n"
                "• Mengirim briefing jadwal kuliah harian setiap pagi\n"
                "• Mengunduh materi & mengumpulkan tugas kuliah langsung dari chat Telegram\n"
                "• Memantau IP jaringan, koneksi internet, dan kontrol reboot VM\n\n"
                "Silakan pilih menu di bawah atau klik tombol reset untuk memunculkan tombol kontrol per topik:"
            )
            menu_kb = {
                "inline_keyboard": [
                    [
                        {"text": "📊 Status & Kehadiran", "callback_data": "menu_status"},
                        {"text": "📅 Jadwal Kuliah", "callback_data": "jadwal_today"}
                    ],
                    [
                        {"text": "📚 Unduh Materi Kuliah", "callback_data": "materi_menu"},
                        {"text": "📝 Daftar Tugas Kuliah", "callback_data": "task_page_0"}
                    ],
                    [
                        {"text": "📤 Kumpulkan Tugas", "callback_data": "kumpul_menu"},
                        {"text": "🖥️ Info VM & Jaringan", "callback_data": "server_info"}
                    ],
                    [
                        {"text": "🚀 Pasang / Reset Panel di Semua Topik", "callback_data": "setup_panels_action"}
                    ]
                ]
            }

        if message_id:
            self.telegram.edit_message_text(target_chat, message_id, text, reply_markup=menu_kb)
        else:
            self.telegram.send_message(text, reply_markup=menu_kb, chat_id=target_chat, message_thread_id=message_thread_id)


    def send_or_edit_status(self, message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Menyiapkan dan mengirim/mengedit pesan status bot & kehadiran."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_status_id

        if not self.client.ensure_authenticated():
            err_detail = self.client.last_error_detail or "Perlu Login Ulang (Sesi Expired)"
            err_text = (
                "📊 <b>Status AutoAbsen Bot</b>\n\n"
                "👤 <b>Mahasiswa</b>: -\n"
                "🆔 <b>NRP</b>: -\n"
                f"🔴 <b>Status ETHOL</b>: <b>{html.escape(err_detail)}</b>\n"
                f"🕒 <b>Pengecekan Terakhir</b>: {self.last_check_time}\n"
                f"⏱️ <b>Interval Polling</b>: Setiap {self.interval} detik\n"
                f"📝 <b>Total Presensi Tersimpan</b>: {len(self.attended_keys)} sesi"
            )
            inline_keyboard = {
                "inline_keyboard": [
                    [{"text": "🔄 Coba Lagi / Re-login", "callback_data": "menu_status"}]
                ]
            }
            if message_id:
                self.telegram.edit_message_text(target_chat, message_id, err_text, reply_markup=inline_keyboard)
                self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
            else:
                sent = self.telegram.send_message(err_text, reply_markup=inline_keyboard, chat_id=target_chat, message_thread_id=target_thread)
                if sent:
                    self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)
            return

        nama = self.get_student_name()
        nrp = self.get_student_nrp()
        courses = self.client.get_enrolled_courses()
        total_courses = len(courses)
        stats = self.client.get_student_stats() or {}
        rata_hadir = stats.get("rataHadir", 100)
        total_sesi = stats.get("totalSesi")

        status_text = self.telegram.format_status_text(
            nama=nama,
            nrp=nrp,
            is_ethol_active=self.client.is_logged_in(),
            total_courses=total_courses,
            rata_hadir=rata_hadir,
            total_sesi=total_sesi,
            last_check_time=self.last_check_time,
            interval=self.interval,
            total_attended_keys=len(self.attended_keys)
        )

        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🔄 Segarkan Status Kehadiran", "callback_data": "menu_status"}
                ]
            ]
        }

        if message_id:
            self.telegram.edit_message_text(target_chat, message_id, status_text, reply_markup=inline_keyboard)
            self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
        else:
            sent = self.telegram.send_message(status_text, reply_markup=inline_keyboard, chat_id=target_chat, message_thread_id=target_thread)
            if sent:
                self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)

    def send_or_edit_tasks(self, page: int = 0, message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Mengambil daftar tugas kuliah dan menampilkannya dengan format per matakuliah & pagination."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_tugas_id

        if not self.client.ensure_authenticated():
            err_msg = "⚠️ <b>Sesi ETHOL kedaluwarsa.</b> Bot sedang mencoba login ulang, silakan tunggu beberapa saat."
            if message_id:
                self.telegram.edit_message_text(target_chat, message_id, err_msg)
                self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
            else:
                sent = self.telegram.send_message(err_msg, chat_id=target_chat, message_thread_id=target_thread)
                if sent:
                    self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)
            return

        tasks = self.client.get_pending_tasks()
        text, inline_keyboard, _ = self.telegram.format_tasks_by_course(tasks, page=page, courses_per_page=2)

        if message_id:
            self.telegram.edit_message_text(target_chat, message_id, text, reply_markup=inline_keyboard)
            self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
        else:
            sent = self.telegram.send_message(text, reply_markup=inline_keyboard, chat_id=target_chat, message_thread_id=target_thread)
            if sent:
                self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)

    def send_or_edit_schedule(self, view_mode: str = "today", message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Menampilkan jadwal perkuliahan hari ini atau seluruh semester."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_jadwal_id

        if not self.client.ensure_authenticated():
            err_msg = "⚠️ <b>Sesi ETHOL kedaluwarsa.</b> Silakan coba lagi beberapa saat."
            if message_id:
                self.telegram.edit_message_text(target_chat, message_id, err_msg)
                self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
            else:
                sent = self.telegram.send_message(err_msg, chat_id=target_chat, message_thread_id=target_thread)
                if sent:
                    self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)
            return

        if view_mode == "today":
            items = self.client.get_today_schedule()
        else:
            items = self.client.get_student_schedule()

        current_time = self.get_current_time_str()
        text, kb = self.telegram.format_schedule(items, current_time, view_mode=view_mode)

        if message_id:
            self.telegram.edit_message_text(target_chat, message_id, text, reply_markup=kb)
            self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
        else:
            sent = self.telegram.send_message(text, reply_markup=kb, chat_id=target_chat, message_thread_id=target_thread)
            if sent:
                self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)

    def send_or_edit_kumpul_courses(self, message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Menampilkan pilihan mata kuliah untuk memulai proses pengumpulan tugas."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_tugas_id

        if not self.client.ensure_authenticated():
            err_msg = "⚠️ <b>Sesi ETHOL kedaluwarsa.</b> Silakan coba lagi beberapa saat."
            if message_id:
                self.telegram.edit_message_text(target_chat, message_id, err_msg)
                self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
            else:
                sent = self.telegram.send_message(err_msg, chat_id=target_chat, message_thread_id=target_thread)
                if sent:
                    self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)
            return

        courses = self.client.get_enrolled_courses()
        text, kb = self.telegram.format_courses_for_submission(courses)

        if message_id:
            self.telegram.edit_message_text(target_chat, message_id, text, reply_markup=kb)
            self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
        else:
            sent = self.telegram.send_message(text, reply_markup=kb, chat_id=target_chat, message_thread_id=target_thread)
            if sent:
                self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)

    def send_or_edit_kumpul_tasks(self, kuliah_id: int, message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Menampilkan daftar tugas dalam mata kuliah yang dipilih."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_tugas_id

        if not self.client.ensure_authenticated():
            err_msg = "⚠️ <b>Sesi ETHOL kedaluwarsa.</b> Silakan coba lagi."
            if message_id:
                self.telegram.edit_message_text(target_chat, message_id, err_msg)
                self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
            else:
                sent = self.telegram.send_message(err_msg, chat_id=target_chat, message_thread_id=target_thread)
                if sent:
                    self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)
            return

        courses = self.client.get_enrolled_courses()
        course_obj = next((c for c in courses if c.get("nomor") == kuliah_id), {})
        course_name = (
            course_obj.get("matakuliah", {}).get("nama")
            or course_obj.get("nama")
            or f"Matakuliah #{kuliah_id}"
        )

        tasks = self.client.get_tasks_for_course(kuliah_id)
        text, kb = self.telegram.format_tasks_for_submission(course_name, tasks, kuliah_id)

        if message_id:
            self.telegram.edit_message_text(target_chat, message_id, text, reply_markup=kb)
            self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
        else:
            sent = self.telegram.send_message(text, reply_markup=kb, chat_id=target_chat, message_thread_id=target_thread)
            if sent:
                self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)

    def prompt_kumpul_file(self, kuliah_id: int, id_tugas: int, message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Menyimpan session upload dan meminta pengguna mengirimkan file tugas."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_tugas_id

        courses = self.client.get_enrolled_courses()
        course_obj = next((c for c in courses if c.get("nomor") == kuliah_id), {})
        course_name = (
            course_obj.get("matakuliah", {}).get("nama")
            or course_obj.get("nama")
            or f"Matakuliah #{kuliah_id}"
        )

        tasks = self.client.get_tasks_for_course(kuliah_id)
        task_obj = next((t for t in tasks if str(t.get("nomor") or t.get("id") or t.get("id_tugas")) == str(id_tugas)), {})

        task_title = task_obj.get("judul") or task_obj.get("title") or f"Tugas #{id_tugas}"
        deadline = task_obj.get("deadline") or task_obj.get("tgl_deadline") or "Tidak ditentukan"
        is_closed = task_obj.get("tutup") == 1
        is_submitted = bool(task_obj.get("nomor_tugas_mahasiswa") or task_obj.get("submission_time"))
        nomor_tugas_mahasiswa = task_obj.get("nomor_tugas_mahasiswa")
        nomor_tugas_file_mahasiswa = task_obj.get("nomor_tugas_file_mahasiswa")

        self.active_upload_session = {
            "kuliah_id": kuliah_id,
            "id_tugas": id_tugas,
            "course_name": course_name,
            "task_title": task_title,
            "deadline": deadline,
            "is_closed": is_closed,
            "is_submitted": is_submitted,
            "nomor_tugas_mahasiswa": nomor_tugas_mahasiswa,
            "nomor_tugas_file_mahasiswa": nomor_tugas_file_mahasiswa,
            "chat_id": target_chat,
            "message_thread_id": target_thread,
            "created_at": time.time()
        }

        text, kb = self.telegram.format_waiting_file_prompt(
            course_name=course_name,
            task_title=task_title,
            deadline=deadline,
            is_submitted=is_submitted,
            is_closed=is_closed
        )

        prompt_msg_id = message_id
        if message_id:
            ok = self.telegram.edit_message_text(target_chat, message_id, text, reply_markup=kb)
            if not ok:
                self.telegram.edit_message_reply_markup(target_chat, message_id, None)
                sent = self.telegram.send_message(text, reply_markup=kb, chat_id=target_chat, message_thread_id=target_thread)
                if sent:
                    prompt_msg_id = sent.get("message_id")
        else:
            sent = self.telegram.send_message(text, reply_markup=kb, chat_id=target_chat, message_thread_id=target_thread)
            if sent:
                prompt_msg_id = sent.get("message_id")

        self.active_upload_session["prompt_message_id"] = prompt_msg_id
        self.set_active_ui(prompt_msg_id)

    def check_ui_inactivity_timeout(self):
        """
        Memeriksa apakah pengguna berada di sub-menu (misal memilih matakuliah/materi/tugas/upload)
        namun idle tanpa ada aktivitas lanjutan. Jika idle selama 3 menit (180 detik),
        kembalikan tampilan pesan ke panel awal topik tersebut secara otomatis!
        """
        if not self.active_ui_session:
            return

        session = self.active_ui_session
        last_activity = session.get("last_activity")
        if not last_activity:
            return

        elapsed = time.time() - last_activity
        if elapsed >= self.ui_timeout_seconds:
            msg_id = session.get("message_id")
            thread_id = session.get("message_thread_id")
            target_chat = session.get("chat_id") or self.chat_id

            self.active_ui_session = None
            self.active_upload_session = None

            logger.info("Inactivity timeout (%d detik) pada thread %s. Mengembalikan tampilan ke panel awal topik.", int(elapsed), thread_id)
            if msg_id:
                nama = self.get_student_name()
                nrp = self.get_student_nrp()

                # Kembalikan ke panel awal sesuai topik masing-masing
                if thread_id == self.topic_materi_id and self.topic_materi_id is not None:
                    txt, kb = self.telegram.format_topic_panel_materi(nama, nrp)
                    self.telegram.edit_message_text(target_chat, msg_id, txt, reply_markup=kb)
                elif thread_id == self.topic_tugas_id and self.topic_tugas_id is not None:
                    pending_tasks = self.client.get_pending_tasks()
                    txt, kb = self.telegram.format_topic_panel_tugas(nama, nrp, pending_count=len(pending_tasks))
                    self.telegram.edit_message_text(target_chat, msg_id, txt, reply_markup=kb)
                elif thread_id == self.topic_jadwal_id and self.topic_jadwal_id is not None:
                    txt, kb = self.telegram.format_topic_panel_jadwal(nama, nrp)
                    self.telegram.edit_message_text(target_chat, msg_id, txt, reply_markup=kb)
                elif thread_id == self.topic_server_id and self.topic_server_id is not None:
                    txt, kb = self.telegram.format_topic_panel_server()
                    self.telegram.edit_message_text(target_chat, msg_id, txt, reply_markup=kb)
                elif thread_id == self.topic_status_id and self.topic_status_id is not None:
                    courses = self.client.get_enrolled_courses()
                    stats = self.client.get_student_stats() or {}
                    rata_hadir = stats.get("rataHadir", 100)
                    txt, kb = self.telegram.format_topic_panel_status(
                        nama, nrp, len(courses), rata_hadir, self.client.is_logged_in(), self.last_check_time
                    )
                    self.telegram.edit_message_text(target_chat, msg_id, txt, reply_markup=kb)
                elif thread_id == self.topic_presensi_id and self.topic_presensi_id is not None:
                    courses = self.client.get_enrolled_courses()
                    txt, kb = self.telegram.format_topic_panel_presensi(nama, nrp, len(courses), len(self.attended_keys))
                    self.telegram.edit_message_text(target_chat, msg_id, txt, reply_markup=kb)
                else:
                    self.send_or_edit_main_menu(message_id=msg_id, chat_id=target_chat)

    def send_or_edit_materi_courses(self, message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Menampilkan daftar mata kuliah untuk melihat & mengunduh materi perkuliahan."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_materi_id

        if not self.client.ensure_authenticated():
            err_msg = "⚠️ <b>Sesi ETHOL kedaluwarsa.</b> Silakan coba lagi beberapa saat."
            if message_id:
                self.telegram.edit_message_text(target_chat, message_id, err_msg)
                self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
            else:
                sent = self.telegram.send_message(err_msg, chat_id=target_chat, message_thread_id=target_thread)
                if sent:
                    self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)
            return

        courses = self.client.get_enrolled_courses()
        text, kb = self.telegram.format_materials_course_list(courses)

        if message_id:
            self.telegram.edit_message_text(target_chat, message_id, text, reply_markup=kb)
            self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
        else:
            sent = self.telegram.send_message(text, reply_markup=kb, chat_id=target_chat, message_thread_id=target_thread)
            if sent:
                self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)

    def send_or_edit_materi_list(self, kuliah_id: int, message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Menampilkan daftar materi/file untuk mata kuliah yang dipilih."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_materi_id

        if not self.client.ensure_authenticated():
            err_msg = "⚠️ <b>Sesi ETHOL kedaluwarsa.</b> Silakan coba lagi."
            if message_id:
                self.telegram.edit_message_text(target_chat, message_id, err_msg)
                self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
            else:
                sent = self.telegram.send_message(err_msg, chat_id=target_chat, message_thread_id=target_thread)
                if sent:
                    self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)
            return

        courses = self.client.get_enrolled_courses()
        course_obj = next((c for c in courses if c.get("nomor") == kuliah_id), {})
        course_name = (
            course_obj.get("matakuliah", {}).get("nama")
            or course_obj.get("nama")
            or f"Matakuliah #{kuliah_id}"
        )

        materials = self.client.get_course_materials(kuliah_id)
        text, kb = self.telegram.format_course_materials(course_name, materials, kuliah_id)

        if message_id:
            self.telegram.edit_message_text(target_chat, message_id, text, reply_markup=kb)
            self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
        else:
            sent = self.telegram.send_message(text, reply_markup=kb, chat_id=target_chat, message_thread_id=target_thread)
            if sent:
                self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)

    def handle_download_material(self, materi_id: int, kuliah_id: int, chat_id: Any, message_thread_id: Optional[int] = None):
        """Mengunduh dan mengirimkan file materi langsung ke pengguna Telegram."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_materi_id

        if not self.client.ensure_authenticated():
            self.telegram.send_message("⚠️ <b>Sesi ETHOL kedaluwarsa.</b> Silakan coba lagi.", chat_id=target_chat, message_thread_id=target_thread)
            return

        courses = self.client.get_enrolled_courses()
        course_obj = next((c for c in courses if c.get("nomor") == kuliah_id), {})
        course_name = (
            course_obj.get("matakuliah", {}).get("nama")
            or course_obj.get("nama")
            or f"Matakuliah #{kuliah_id}"
        )

        materials = self.client.get_course_materials(kuliah_id)
        mat_obj = next((m for m in materials if m.get("id") == materi_id), None)
        if not mat_obj:
            self.telegram.send_message("❌ <b>Materi tidak ditemukan</b> di server ETHOL.", chat_id=target_chat, message_thread_id=target_thread)
            return

        title = mat_obj.get("title") or mat_obj.get("judul") or "Materi Perkuliahan"
        file_path = mat_obj.get("path")
        tipe = mat_obj.get("tipe", 1)

        if tipe == 2 or (file_path and not file_path.startswith("http") and "upload" not in file_path):
            msg = (
                f"🔗 <b>LINK MATERI PERKULIAHAN</b>\n\n"
                f"📚 <b>Matakuliah</b> : {html.escape(str(course_name))}\n"
                f"📑 <b>Judul</b>      : {html.escape(str(title))}\n"
                f"🌐 <b>Tautan URL</b>  : <a href=\"{html.escape(str(file_path))}\">{html.escape(str(file_path))}</a>"
            )
            self.telegram.send_message(msg, chat_id=target_chat, message_thread_id=target_thread)
            return

        status_msg = self.telegram.send_message(
            f"⏳ <i>Sedang mengunduh file materi <b>{html.escape(str(title))}</b> dari ETHOL...</i>",
            chat_id=target_chat,
            message_thread_id=target_thread
        )

        file_data = self.client.download_material_file(file_path)
        if status_msg and status_msg.get("message_id"):
            self.telegram.edit_message_reply_markup(target_chat, status_msg["message_id"], None)

        if not file_data:
            self.telegram.send_message(
                f"❌ <b>Gagal mengunduh file materi</b> dari server ETHOL: {html.escape(str(title))}",
                chat_id=target_chat,
                message_thread_id=target_thread
            )
            return

        file_name, file_bytes = file_data
        caption = (
            f"📄 <b>{html.escape(str(title))}</b>\n\n"
            f"📚 <b>Matakuliah</b> : {html.escape(str(course_name))}\n"
            f"🕒 <b>Diunggah</b>   : {html.escape(str(mat_obj.get('created_indonesia') or '-'))}\n"
            "<i>Diunduh via AutoAbsen ETHOL Bot</i>"
        )
        self.telegram.send_document(
            document=(file_name, file_bytes),
            caption=caption,
            chat_id=target_chat,
            message_thread_id=target_thread
        )

    def send_or_edit_server_info(self, message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Menampilkan status IP, konektivitas internet, memory, dan kontrol VM."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_server_id

        interfaces = system_diagnostic.get_network_interfaces()
        connections = system_diagnostic.test_connection()
        resources = system_diagnostic.get_system_resources()
        current_time = self.get_current_time_str()

        text, kb = self.telegram.format_server_info(
            interfaces=interfaces,
            connections=connections,
            resources=resources,
            current_time=current_time
        )

        if message_id:
            self.telegram.edit_message_text(target_chat, message_id, text, reply_markup=kb)
            self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
        else:
            sent = self.telegram.send_message(text, reply_markup=kb, chat_id=target_chat, message_thread_id=target_thread)
            if sent:
                self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)

    def check_active_presensi_now(self, message_id: int = None, chat_id: Optional[Any] = None, message_thread_id: Optional[int] = None):
        """Memeriksa secara langsung apakah ada sesi presensi yang sedang dibuka oleh dosen."""
        target_chat = chat_id or self.chat_id
        target_thread = message_thread_id if message_thread_id is not None else self.topic_presensi_id

        if not self.client.ensure_authenticated():
            err_msg = "⚠️ <b>Sesi ETHOL kedaluwarsa.</b> Silakan coba lagi beberapa saat."
            if message_id:
                self.telegram.edit_message_text(target_chat, message_id, err_msg)
            else:
                self.telegram.send_message(err_msg, chat_id=target_chat, message_thread_id=target_thread)
            return

        courses = self.client.get_enrolled_courses()
        current_time_str = self.get_current_time_str()
        active_list = []

        for c in courses:
            kid = c.get("nomor")
            active = self.client.get_active_presensi(kid)
            if active:
                mk_name = c.get("matakuliah", {}).get("nama") or c.get("nama") or f"Matakuliah #{kid}"
                dosen = c.get("dosen") or "-"
                active_list.append((mk_name, dosen, active))

        if active_list:
            lines = [
                "🔔 <b>SESI PRESENSI AKTIF DITEMUKAN!</b>\n",
                f"🕒 <i>{current_time_str}</i>\n"
            ]
            for idx, (mk, dsn, act) in enumerate(active_list, 1):
                buka = act.get("waktu_buka") or "Sekarang"
                lines.append(f"<b>{idx}. {html.escape(str(mk))}</b>")
                lines.append(f"   👨‍🏫 <b>Dosen</b> : {html.escape(str(dsn))}")
                lines.append(f"   🕒 <b>Dibuka</b> : {html.escape(str(buka))}")
                lines.append("   🟢 <b>Status</b> : Sedang Dibuka Dosen")
                lines.append("")
            lines.append("🤖 <i>Bot AutoAbsen otomatis melakukan presensi jika belum tercatat.</i>")
            text = "\n".join(lines)
        else:
            text = (
                "ℹ️ <b>TIDAK ADA PRESENSI AKTIF</b>\n\n"
                f"🕒 <i>{current_time_str}</i>\n\n"
                "Saat ini belum ada dosen yang membuka sesi presensi di ETHOL.\n"
                "Bot tetap aktif memantau di latar belakang 24/7."
            )

        kb = {
            "inline_keyboard": [
                [
                    {"text": "🔄 Cek Ulang Presensi", "callback_data": "presensi_check_active"},
                    {"text": "📊 Status Kehadiran", "callback_data": "menu_status"}
                ]
            ]
        }

        if message_id:
            self.telegram.edit_message_text(target_chat, message_id, text, reply_markup=kb)
            self.set_active_ui(message_id, chat_id=target_chat, message_thread_id=target_thread)
        else:
            sent = self.telegram.send_message(text, reply_markup=kb, chat_id=target_chat, message_thread_id=target_thread)
            if sent:
                self.set_active_ui(sent.get("message_id"), chat_id=target_chat, message_thread_id=target_thread)

    def setup_topic_panels(self, chat_id: Optional[Any] = None):
        """Memasang control panel interaktif di semua topik yang telah dikonfigurasi di .env."""
        target_chat = chat_id or self.chat_id
        nama = self.get_student_name()
        nrp = self.get_student_nrp()
        courses = self.client.get_enrolled_courses()
        total_courses = len(courses)
        stats = self.client.get_student_stats() or {}
        rata_hadir = stats.get("rataHadir", 100)
        pending_tasks = self.client.get_pending_tasks()
        pending_count = len(pending_tasks)

        deployed = []

        # 1. Topik Presensi
        if self.topic_presensi_id:
            txt, kb = self.telegram.format_topic_panel_presensi(nama, nrp, total_courses, len(self.attended_keys))
            self.telegram.send_message(txt, reply_markup=kb, chat_id=target_chat, message_thread_id=self.topic_presensi_id)
            deployed.append("🔔 Presensi")

        # 2. Topik Materi Baru
        if self.topic_materi_id:
            txt, kb = self.telegram.format_topic_panel_materi(nama, nrp)
            self.telegram.send_message(txt, reply_markup=kb, chat_id=target_chat, message_thread_id=self.topic_materi_id)
            deployed.append("📚 Materi Baru")

        # 3. Topik Tugas Baru & Kumpul Tugas
        if self.topic_tugas_id:
            txt, kb = self.telegram.format_topic_panel_tugas(nama, nrp, pending_count=pending_count)
            self.telegram.send_message(txt, reply_markup=kb, chat_id=target_chat, message_thread_id=self.topic_tugas_id)
            deployed.append("📝 Tugas Baru & Kumpul Tugas")

        # 4. Topik Jadwal Kuliah
        if self.topic_jadwal_id:
            txt, kb = self.telegram.format_topic_panel_jadwal(nama, nrp)
            self.telegram.send_message(txt, reply_markup=kb, chat_id=target_chat, message_thread_id=self.topic_jadwal_id)
            deployed.append("📅 Jadwal Kuliah")

        # 5. Topik Info & Kontrol VM
        if self.topic_server_id:
            txt, kb = self.telegram.format_topic_panel_server()
            self.telegram.send_message(txt, reply_markup=kb, chat_id=target_chat, message_thread_id=self.topic_server_id)
            deployed.append("🖥️ Info & Kontrol VM")

        # 6. Topik Status Kehadiran
        if self.topic_status_id:
            txt, kb = self.telegram.format_topic_panel_status(
                nama, nrp, total_courses, rata_hadir, self.client.is_logged_in(), self.last_check_time
            )
            self.telegram.send_message(txt, reply_markup=kb, chat_id=target_chat, message_thread_id=self.topic_status_id)
            deployed.append("📊 Status Kehadiran")

        if deployed:
            summary = (
                "✅ <b>SETUP PANEL SELESAI!</b>\n\n"
                f"Panel kontrol interaktif berhasil dipasang pada <b>{len(deployed)} topik</b>:\n"
                + "\n".join(f"• {d}" for d in deployed) + "\n\n"
                "<i>Silakan cek masing-masing topik forum untuk menggunakan tombol menu.</i>"
            )
        else:
            summary = (
                "⚠️ <b>Belum ada ID Topik yang dikonfigurasi di file <code>.env</code>!</b>\n\n"
                "Ketik <code>/getid</code> di dalam masing-masing topik forum Telegram Anda, lalu masukkan nilainya ke <code>.env</code>."
            )
        self.telegram.send_message(summary, chat_id=target_chat)

    def handle_telegram_commands(self):
        """Memproses interaksi pengguna di Telegram (pesan teks, file dokumen, dan klik tombol inline)."""
        updates = self.telegram.get_updates(offset=self.tele_offset, timeout=0)
        for upd in updates:
            self.tele_offset = upd["update_id"] + 1

            # 1. Handle Callback Query (Klik tombol inline)
            callback_query = upd.get("callback_query")
            if callback_query:
                cb_id = callback_query["id"]
                data = str(callback_query.get("data", ""))
                from_id = str(callback_query.get("from", {}).get("id", ""))
                msg_obj = callback_query.get("message", {})
                message_id = msg_obj.get("message_id")
                cb_chat_id = str(msg_obj.get("chat", {}).get("id", ""))
                cb_thread_id = msg_obj.get("message_thread_id")

                # Cek otorisasi
                if cb_chat_id != self.chat_id and from_id != self.chat_id:
                    self.telegram.answer_callback_query(cb_id, text="Akses tidak diizinkan")
                    continue

                self.telegram.answer_callback_query(cb_id)

                if data == "menu_main":
                    self.send_or_edit_main_menu(message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                elif data == "menu_status":
                    self.send_or_edit_status(message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                elif data in ["jadwal_today", "jadwal_refresh"]:
                    self.send_or_edit_schedule(view_mode="today", message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                elif data == "jadwal_all":
                    self.send_or_edit_schedule(view_mode="all", message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                elif data.startswith("task_page_"):
                    try:
                        p = int(data.split("_")[-1])
                    except Exception:
                        p = 0
                    self.send_or_edit_tasks(page=p, message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                elif data == "materi_menu":
                    self.send_or_edit_materi_courses(message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                elif data.startswith("materi_course_"):
                    try:
                        kid = int(data.split("_")[-1])
                        self.send_or_edit_materi_list(kuliah_id=kid, message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                    except Exception as e:
                        logger.error("Error materi_course callback: %s", e)
                elif data.startswith("materi_dl_"):
                    try:
                        parts = data.split("_")
                        mid = int(parts[2])
                        kid = int(parts[3])
                        self.handle_download_material(materi_id=mid, kuliah_id=kid, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                    except Exception as e:
                        logger.error("Error materi_dl callback: %s", e)
                elif data == "kumpul_menu":
                    self.send_or_edit_kumpul_courses(message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                elif data.startswith("kumpul_course_"):
                    try:
                        kid = int(data.split("_")[-1])
                        self.send_or_edit_kumpul_tasks(kuliah_id=kid, message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                    except Exception as e:
                        logger.error("Error kumpul_course callback: %s", e)
                elif data.startswith("kumpul_task_"):
                    try:
                        parts = data.split("_")
                        kid = int(parts[2])
                        tid = int(parts[3])
                        self.prompt_kumpul_file(kuliah_id=kid, id_tugas=tid, message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                    except Exception as e:
                        logger.error("Error kumpul_task callback: %s", e)
                elif data == "kumpul_cancel":
                    self.active_upload_session = None
                    cancel_text = "❌ <b>Pengumpulan tugas dibatalkan.</b>"
                    cancel_kb = {
                        "inline_keyboard": [
                            [{"text": "📤 Kumpulkan Tugas Lain", "callback_data": "kumpul_menu"}],
                            [{"text": "🔙 Menu Utama", "callback_data": "menu_main"}]
                        ]
                    }
                    if message_id:
                        self.telegram.edit_message_text(cb_chat_id, message_id, cancel_text, reply_markup=cancel_kb)
                        self.set_active_ui(message_id)
                    else:
                        sent = self.telegram.send_message(cancel_text, reply_markup=cancel_kb, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                        if sent:
                            self.set_active_ui(sent.get("message_id"))
                elif data == "setup_panels_action":
                    self.setup_topic_panels(chat_id=cb_chat_id)
                elif data in ["server_info", "server_ping"]:
                    self.send_or_edit_server_info(message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                elif data == "server_reboot_confirm":
                    reboot_text, reboot_kb = self.telegram.format_reboot_confirm()
                    if message_id:
                        self.telegram.edit_message_text(cb_chat_id, message_id, reboot_text, reply_markup=reboot_kb)
                        self.set_active_ui(message_id)
                    else:
                        sent = self.telegram.send_message(reboot_text, reply_markup=reboot_kb, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                        if sent:
                            self.set_active_ui(sent.get("message_id"))
                elif data == "server_reboot_execute":
                    logger.warning("Perintah reboot VM diterima dari pengguna via Telegram.")
                    rebooting_msg = (
                        "🔄 <b>Memulai proses restart Ubuntu VM sekarang...</b>\n\n"
                        "Bot AutoAbsen dan jaringan VM akan offline sementara selama ± 1-2 menit saat proses booting.\n"
                        "Bot akan otomatis aktif kembali saat VM selesai menyala. Sampai jumpa! 👋"
                    )
                    if message_id:
                        self.telegram.edit_message_text(cb_chat_id, message_id, rebooting_msg)
                    else:
                        self.telegram.send_message(rebooting_msg, chat_id=cb_chat_id, message_thread_id=cb_thread_id)

                    time.sleep(1.5)
                    system_diagnostic.reboot_vm()
                elif data == "presensi_check_active":
                    self.check_active_presensi_now(message_id=message_id, chat_id=cb_chat_id, message_thread_id=cb_thread_id)
                continue

            # 2. Handle Message (Teks atau Dokumen File)
            msg = upd.get("message", {})
            sender_chat_id = str(msg.get("chat", {}).get("id", ""))
            from_user_id = str(msg.get("from", {}).get("id", ""))
            msg_thread_id = msg.get("message_thread_id")
            raw_text = (msg.get("text") or "").strip()
            clean_text = raw_text.lower()
            # Bersihkan suffix @bot_username jika dikirim dari grup/forum
            cmd = clean_text.split()[0].split("@")[0] if clean_text.startswith("/") else clean_text

            # Perintah universal /getid atau /id (dapat dijalankan di mana saja tanpa blokir)
            if cmd in ["/getid", "/id", "/topicid"]:
                chat_title = msg.get("chat", {}).get("title") or "Private Chat"
                chat_type = msg.get("chat", {}).get("type")
                reply_id = (
                    "🆔 <b>INFORMASI ID TELEGRAM</b>\n\n"
                    f"• <b>Chat / Group ID:</b> <code>{sender_chat_id}</code>\n"
                    f"• <b>Topic ID (message_thread_id):</b> <code>{msg_thread_id or 'General / Non-Topic'}</code>\n"
                    f"• <b>Tipe Chat:</b> <code>{chat_type}</code>\n"
                    f"• <b>Nama Chat:</b> {html.escape(str(chat_title))}\n\n"
                    "💡 <i>Gunakan ID ini untuk melengkapi file <code>.env</code> pada bot AutoAbsen.</i>"
                )
                self.telegram.send_message(reply_id, chat_id=sender_chat_id, message_thread_id=msg_thread_id)
                continue

            # Cek otorisasi untuk pesan lainnya
            if sender_chat_id != self.chat_id and from_user_id != self.chat_id:
                continue

            # A. Cek Pengiriman File Dokumen / Foto
            doc = msg.get("document")
            photo = msg.get("photo")

            if doc or photo:
                target_chat = sender_chat_id
                target_thread = msg_thread_id or self.topic_tugas_id

                if self.active_upload_session:
                    session = self.active_upload_session
                    id_tugas = session["id_tugas"]
                    course_name = session["course_name"]
                    task_title = session["task_title"]

                    if doc:
                        file_id = doc.get("file_id")
                        file_name = doc.get("file_name") or f"tugas_{id_tugas}.pdf"
                        file_size_kb = (doc.get("file_size") or 0) / 1024.0
                    else:
                        photo_obj = photo[-1]
                        file_id = photo_obj.get("file_id")
                        file_name = f"tugas_{id_tugas}.jpg"
                        file_size_kb = (photo_obj.get("file_size") or 0) / 1024.0

                    prompt_msg_id = session.get("prompt_message_id")
                    if prompt_msg_id:
                        self.telegram.edit_message_reply_markup(target_chat, prompt_msg_id, None)

                    self.telegram.send_message(
                        f"⏳ <i>Sedang mengunduh file <b>{file_name}</b> dan mengunggah ke ETHOL...</i>",
                        chat_id=target_chat,
                        message_thread_id=target_thread
                    )

                    file_data = self.telegram.download_telegram_file(file_id)
                    if not file_data:
                        self.telegram.send_message("❌ <b>Gagal mengunduh file dari Telegram.</b> Silakan coba kirim ulang.", chat_id=target_chat, message_thread_id=target_thread)
                        continue

                    _, file_bytes = file_data
                    is_update = session.get("is_submitted", False)
                    nomor_tugas_mahasiswa = session.get("nomor_tugas_mahasiswa")
                    nomor_tugas_file_mahasiswa = session.get("nomor_tugas_file_mahasiswa")

                    upload_res = self.client.submit_task_file(
                        id_tugas=id_tugas,
                        file_name=file_name,
                        file_bytes=file_bytes,
                        nomor_tugas_mahasiswa=nomor_tugas_mahasiswa,
                        nomor_tugas_file_mahasiswa=nomor_tugas_file_mahasiswa
                    )

                    is_success = upload_res.get("sukses") is True or upload_res.get("sukses") == 1
                    if is_success:
                        self.active_upload_session = None
                        waktu_submit = self.get_current_time_str()
                        self.telegram.notify_task_submit_success(
                            course_name=course_name,
                            task_title=task_title,
                            file_name=file_name,
                            file_size_kb=file_size_kb,
                            upload_time=waktu_submit,
                            is_update=is_update
                        )
                    else:
                        err_msg = upload_res.get("pesan", "Server ETHOL menolak pengunggahan")
                        self.telegram.notify_task_submit_failed(
                            course_name=course_name,
                            task_title=task_title,
                            file_name=file_name,
                            error_msg=err_msg
                        )
                else:
                    unprompted_msg = (
                        "ℹ️ <i>Kamu mengirimkan file, namun belum memilih tugas yang ingin dikumpulkan.</i>\n\n"
                        "Silakan klik tombol <b>📤 Kumpulkan Tugas</b> di bawah untuk memilih mata kuliah & tugas terlebih dahulu."
                    )
                    unprompted_kb = {
                        "inline_keyboard": [
                            [{"text": "📤 Kumpulkan Tugas", "callback_data": "kumpul_menu"}]
                        ]
                    }
                    self.telegram.send_message(unprompted_msg, reply_markup=unprompted_kb, chat_id=target_chat, message_thread_id=target_thread)
                continue

            # B. Handle Text Messages
            if not raw_text:
                continue

            if cmd in ["/setup_panels", "/reset_panels", "/init_topics", "setup"]:
                self.setup_topic_panels(chat_id=sender_chat_id)
            elif cmd in ["/status", "status"] or clean_text == "📊 status":
                self.send_or_edit_status(chat_id=sender_chat_id, message_thread_id=msg_thread_id)
            elif cmd in ["/jadwal", "jadwal"] or clean_text in ["📅 jadwal kuliah", "📅 jadwal"]:
                self.send_or_edit_schedule(view_mode="today", chat_id=sender_chat_id, message_thread_id=msg_thread_id)
            elif cmd in ["/materi", "materi", "/download", "/unduh"] or clean_text in ["📚 materi", "📚 unduh materi kuliah"]:
                self.send_or_edit_materi_courses(chat_id=sender_chat_id, message_thread_id=msg_thread_id)
            elif cmd in ["/tugas", "tugas"] or clean_text in ["📝 tugas", "📝 daftar tugas"]:
                self.send_or_edit_tasks(page=0, chat_id=sender_chat_id, message_thread_id=msg_thread_id)
            elif cmd in ["/kumpul", "kumpul"] or clean_text == "📤 kumpulkan tugas":
                self.send_or_edit_kumpul_courses(chat_id=sender_chat_id, message_thread_id=msg_thread_id)
            elif cmd in ["/server", "server", "vm"] or clean_text in ["🖥️ info server & vm", "🖥️ info vm & server"]:
                self.send_or_edit_server_info(chat_id=sender_chat_id, message_thread_id=msg_thread_id)
            elif cmd in ["/presensi", "presensi"]:
                self.check_active_presensi_now(chat_id=sender_chat_id, message_thread_id=msg_thread_id)
            elif cmd in ["/start", "/menu", "menu", "/panel", "/panels", "/reset", "reset", "/help"]:
                self.send_or_edit_main_menu(chat_id=sender_chat_id, message_thread_id=msg_thread_id)

    def check_morning_briefing(self):
        """
        Mengirimkan briefing jadwal kuliah pagi hari secara otomatis (antara jam 06:00 - 08:00 WIB).
        Hanya dikirim sekali setiap hari.
        """
        now = datetime.now(self.tz)
        today_str = now.strftime("%Y-%m-%d")

        if 6 <= now.hour <= 8 and self.last_morning_briefing_date != today_str:
            if not self.client.ensure_authenticated():
                return
            today_schedule = self.client.get_today_schedule()
            date_display = format_id_datetime(now, with_clock=False)
            logger.info("Mengirimkan briefing jadwal kuliah pagi untuk %s...", date_display)
            self.telegram.notify_morning_briefing(today_schedule, date_display)
            self.last_morning_briefing_date = today_str

    def process_feed_notifications(self, notifications: list):
        """
        Memeriksa feed notifikasi ETHOL untuk Tugas Baru dan Materi Baru.
        Mengirim notifikasi ke Telegram secara otomatis jika ada item baru.
        """
        if not notifications:
            return

        # Jika baru pertama kali dijalankan, rekam ID notifikasi lama agar tidak spamming pesan di awal
        if not self.has_initialized_notifs:
            for notif in notifications:
                nid = notif.get("idNotifikasi")
                if nid:
                    self.notified_notif_ids.add(str(nid))
            save_notified_notifs(self.notified_notif_ids)
            self.has_initialized_notifs = True
            logger.info("Inisialisasi riwayat notifikasi: %s notifikasi lama tercatat.", len(self.notified_notif_ids))
            return

        # Proses notifikasi dari yang paling lama ke yang terbaru
        for notif in reversed(notifications):
            nid = str(notif.get("idNotifikasi") or "")
            if not nid or nid in self.notified_notif_ids:
                continue

            kode = str(notif.get("kodeNotifikasi", "")).upper()
            ket = str(notif.get("keterangan", "")).strip()
            waktu_str = notif.get("createdAtIndonesia") or notif.get("waktuNotifikasi") or self.get_current_time_str()

            # 1. Notifikasi Tugas Baru
            if "TUGAS" in kode or "tugas baru" in ket.lower():
                m = re.search(r"matakuliah\s+(.*?)\s+dengan judul\s+(.*)", ket, re.IGNORECASE)
                if m:
                    mk_name = m.group(1).strip()
                    judul = m.group(2).strip()
                else:
                    mk_name = "Mata Kuliah"
                    judul = ket

                logger.info("Notifikasi Tugas Baru terdeteksi: %s (%s)", judul, mk_name)
                self.telegram.notify_new_task(
                    matakuliah=mk_name,
                    judul=judul,
                    waktu_upload=waktu_str
                )
                self.notified_notif_ids.add(nid)
                save_notified_notifs(self.notified_notif_ids)

            # 2. Notifikasi Materi Baru
            elif "MATERI" in kode or "materi baru" in ket.lower():
                m = re.search(r"judul\s+(.*?)\s+telah ditambahkan oleh Dosen untuk matakuliah\s+(.*)", ket, re.IGNORECASE)
                if m:
                    judul = m.group(1).strip()
                    mk_name = m.group(2).strip()
                else:
                    judul = "Materi Perkuliahan"
                    mk_name = ket

                url_web = notif.get("urlWeb", "")
                kuliah_match = re.search(r"/matakuliah/(\d+)", url_web)
                kuliah_id = int(kuliah_match.group(1)) if kuliah_match else None

                logger.info("Notifikasi Materi Baru terdeteksi: %s (%s, Kuliah ID: %s)", judul, mk_name, kuliah_id)
                self.telegram.notify_new_material(
                    matakuliah=mk_name,
                    judul=judul,
                    waktu_upload=waktu_str,
                    kuliah_id=kuliah_id
                )
                self.notified_notif_ids.add(nid)
                save_notified_notifs(self.notified_notif_ids)

    def check_and_attend(self) -> int:
        """Pemeriksaan notifikasi, materi/tugas baru, briefing pagi, dan eksekusi presensi aktif secara otomatis."""
        self.last_check_time = self.get_current_time_str()
        logger.info("Memeriksa status presensi dan notifikasi ETHOL...")

        # Cek dan kirim briefing jadwal pagi jika waktunya tiba
        self.check_morning_briefing()

        if not self.client.ensure_authenticated():
            logger.error("Gagal autentikasi ke ETHOL.")
            return 0

        presensi_acted = 0

        # Ambil daftar seluruh mata kuliah semester aktif
        courses = self.client.get_enrolled_courses()
        course_map = {c.get("nomor"): c for c in courses if c.get("nomor")}

        # Ambil notifikasi untuk mendeteksi pembukaan presensi, tugas baru, dan materi baru
        notifications = self.client.get_notifications(filter_notif="SEMUA")

        # Proses notifikasi tugas baru dan materi baru
        if notifications:
            self.process_feed_notifications(notifications)

        latest_presensi_notifs: dict = {}

        if notifications:
            for notif in notifications:
                kode = str(notif.get("kodeNotifikasi", "")).upper()
                ket = notif.get("keterangan", "")
                url_web = notif.get("urlWeb", "")

                is_presensi_notif = "PRESENSI" in kode or "presensi" in ket.lower()
                if not is_presensi_notif:
                    continue

                kuliah_match = re.search(r"/matakuliah/(\d+)", url_web)
                if kuliah_match:
                    kid = int(kuliah_match.group(1))
                    # Notifikasi teratas pada list adalah yang paling baru (terkini)
                    if kid not in latest_presensi_notifs:
                        latest_presensi_notifs[kid] = notif

        # Daftar mata kuliah yang akan dicek (prioritaskan yang ada notif presensi, lalu semua matakuliah)
        candidate_kids = list(latest_presensi_notifs.keys())
        for kid in course_map.keys():
            if kid not in candidate_kids:
                candidate_kids.append(kid)

        for kuliah_id in candidate_kids:
            # 1. Ambil detail sesi presensi aktif dari ETHOL
            active_session = self.client.get_active_presensi(kuliah_id=kuliah_id)
            if not active_session:
                continue

            session_key = str(active_session.get("key"))
            unique_tracking_id = f"{kuliah_id}_{session_key}"

            # 2. Cek apakah sesi ini sudah pernah diproses oleh bot
            if unique_tracking_id in self.attended_keys:
                continue

            # 3. Cek juga riwayat di server ETHOL apakah mahasiswa sudah terdata hadir
            riwayat = self.client.get_riwayat_presensi(kuliah_id=kuliah_id)
            already_recorded = any(str(hist.get("key")) == session_key for hist in riwayat)
            if already_recorded:
                logger.info("Sesi presensi %s untuk matakuliah %s sudah tercatat di server.", session_key, kuliah_id)
                self.attended_keys.add(unique_tracking_id)
                save_attended_keys(self.attended_keys)
                continue

            # 4. Ambil informasi lengkap mata kuliah dan dosen
            kuliah_detail = self.client.get_kuliah_detail(kuliah_id=kuliah_id) or course_map.get(kuliah_id, {})
            
            # Ekstrak nama matakuliah
            matakuliah_name = (
                kuliah_detail.get("matakuliah", {}).get("nama")
                or kuliah_detail.get("nama")
                or kuliah_detail.get("nama_matakuliah")
                or f"Matakuliah #{kuliah_id}"
            )

            # Ekstrak nama dosen
            dosen_name = (
                kuliah_detail.get("dosen")
                or kuliah_detail.get("nama_dosen")
                or kuliah_detail.get("pengajar")
            )
            if not dosen_name and isinstance(kuliah_detail.get("dosen_list"), list) and kuliah_detail["dosen_list"]:
                dosen_name = kuliah_detail["dosen_list"][0].get("nama")
            if not dosen_name:
                dosen_name = "Dosen Pengampu"

            # 5. Format waktu buka presensi secara akurat
            notif_info = latest_presensi_notifs.get(kuliah_id, {})
            waktu_notif_str = notif_info.get("waktuNotifikasi", "")
            
            # Jika ada waktu relatif terkini seperti 'detik', 'menit', atau 'jam'
            if waktu_notif_str and any(unit in waktu_notif_str.lower() for unit in ["detik", "menit", "jam"]):
                waktu_buka = waktu_notif_str
            else:
                # Gunakan format waktu Indonesia atau fallback ke waktu saat ini jika sesi memang sedang terbuka sekarang
                waktu_buka = (
                    active_session.get("tanggal_format")
                    or active_session.get("waktu_buka")
                    or notif_info.get("createdAtIndonesia")
                    or "Baru saja (Sesi Terbuka)"
                )

            # 6. Eksekusi Presensi Otomatis
            logger.info("Mengeksekusi presensi otomatis untuk %s (Dosen: %s, Key: %s)...", 
                        matakuliah_name, dosen_name, session_key)
            
            schema = active_session.get("jenisSchema") or active_session.get("jenis_schema") or self.client.get_schema_for_kuliah(kuliah_id)
            result = self.client.submit_presensi(
                kuliah_id=kuliah_id,
                key=active_session.get("key"),
                jenis_schema=schema,
                kuliah_asal=active_session.get("kuliah_asal", kuliah_id)
            )

            waktu_eksekusi = self.get_current_time_str()

            if result.get("sukses"):
                logger.info("Presensi BERHASIL dicatat untuk %s!", matakuliah_name)
                self.attended_keys.add(unique_tracking_id)
                save_attended_keys(self.attended_keys)

                # Tandai notifikasi terkait sebagai terbaca jika ada idNotifikasi
                if notif_info.get("idNotifikasi"):
                    self.client.mark_notification_as_read(notif_info["idNotifikasi"])

                # Kirim notifikasi Telegram
                self.telegram.notify_presensi_success(
                    matakuliah=matakuliah_name,
                    dosen=dosen_name,
                    waktu_buka=waktu_buka,
                    waktu_absen=waktu_eksekusi
                )
                presensi_acted += 1
            else:
                pesan_error = result.get("pesan", "Respon server tidak sukses")
                # Jika pesan error menunjukkan sudah absen sebelumnya
                if "sudah melakukan" in pesan_error.lower() or "sudah presensi" in pesan_error.lower():
                    logger.info("Mahasiswa telah melakukan presensi sebelumnya untuk sesi %s.", session_key)
                    self.attended_keys.add(unique_tracking_id)
                    save_attended_keys(self.attended_keys)
                else:
                    logger.error("Presensi GAGAL untuk %s: %s", matakuliah_name, pesan_error)
                    self.telegram.notify_presensi_failed(
                        matakuliah=matakuliah_name,
                        dosen=dosen_name,
                        waktu_buka=waktu_buka,
                        pesan_gagal=pesan_error
                    )

        return presensi_acted

    def refresh_ethol_session_if_needed(self) -> bool:
        """Pastikan sesi ETHOL selalu aktif di background tanpa perlu logout / intervensi manual."""
        if self.client.is_logged_in():
            self.relogin_retry_delay = 30
            self.next_relogin_at = 0.0
            return True

        now = time.monotonic()
        if now < self.next_relogin_at:
            remaining = int(self.next_relogin_at - now)
            logger.warning("Menunggu cooldown relogin ETHOL (%s detik lagi).", remaining)
            return False

        logger.warning("Sesi ETHOL expired atau belum aktif. Melakukan relogin otomatis...")
        if self.client.login():
            self.relogin_retry_delay = 30
            self.next_relogin_at = 0.0
            logger.info("Relogin otomatis ETHOL berhasil.")
            return True

        self.next_relogin_at = now + self.relogin_retry_delay
        logger.error(
            "Relogin ETHOL gagal. Percobaan berikutnya dalam %s detik.",
            self.relogin_retry_delay
        )
        self.relogin_retry_delay = min(self.relogin_retry_delay * 2, 2 * 60)
        return False

    def run(self):
        """Memulai loop utama bot."""
        logger.info("Memulai AutoAbsen ETHOL Bot...")

        # Daftarkan menu perintah di Telegram [/]
        self.telegram.set_bot_commands()

        # Setup graceful termination
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

        # Login awal
        if not self.refresh_ethol_session_if_needed():
            err_detail = self.client.last_error_detail or "Gagal menghubungi server ETHOL / CAS SSO"
            logger.error("Login awal gagal: %s! Memeriksa ulang dalam interval berikutnya...", err_detail)
            startup_msg = (
                "⚠️ <b>AutoAbsen Bot Dinyalakan, namun Belum Berhasil Masuk ke ETHOL.</b>\n\n"
                f"📌 <b>Status / Detail Masalah:</b>\n<b>{html.escape(err_detail)}</b>\n\n"
                "🤖 <i>Bot akan otomatis mencoba menghubungkan kembali secara berkala di latar belakang.</i>"
            )
            target_thread = self.topic_status_id or self.topic_presensi_id
            self.telegram.send_message(startup_msg, message_thread_id=target_thread)
        else:
            nama = self.get_student_name()
            nrp = self.get_student_nrp()
            logger.info("Bot siap beroperasi untuk %s (NRP: %s).", nama, nrp)
            self.telegram.notify_bot_started(nama=nama, nrp=nrp, check_interval=self.interval)

        while self.is_running:
            try:
                session_ready = self.refresh_ethol_session_if_needed()
                if not session_ready:
                    logger.warning("Relogin otomatis gagal; menunggu siklus berikutnya.")
                else:
                    # Periksa interaksi dan perintah Telegram
                    self.handle_telegram_commands()
                    self.check_ui_inactivity_timeout()

                    # Periksa notifikasi, materi/tugas baru, dan lakukan presensi otomatis
                    self.check_and_attend()
            except Exception as e:
                logger.exception("Terjadi kesalahan pada siklus polling: %s", e)

            # Sleep terbagi agar responsif terhadap klik tombol, pengiriman file, dan timeout
            sleep_step = 2
            elapsed = 0
            while elapsed < self.interval and self.is_running:
                time.sleep(sleep_step)
                elapsed += sleep_step
                # Cek respon Telegram & timeout di sela waktu sleep
                self.handle_telegram_commands()
                self.check_ui_inactivity_timeout()

        logger.info("AutoAbsen Bot dimatikan secara normal.")

    def _handle_exit(self, signum, frame):
        logger.info("Menerima sinyal terminasi (%s). Menghentikan bot...", signum)
        self.is_running = False


if __name__ == "__main__":
    app = AutoAbsenApp()
    app.run()
