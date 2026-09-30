import logging
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Optional, Dict, Any, List, Tuple
import requests

logger = logging.getLogger("ethol_client")


class CasFormParser(HTMLParser):
    """Parser untuk mengekstrak form action dan hidden field 'lt' dari halaman CAS PENS."""
    def __init__(self):
        super().__init__()
        self.action = None
        self.inputs = {}
        self.in_form = False
        self.ticket_url = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "form":
            if attrs_dict.get("id") == "fm1" or "cas/login" in attrs_dict.get("action", ""):
                self.in_form = True
                self.action = attrs_dict.get("action")
        elif tag == "input" and self.in_form:
            name = attrs_dict.get("name")
            val = attrs_dict.get("value", "")
            if name:
                self.inputs[name] = val
        elif tag == "a":
            href = attrs_dict.get("href", "")
            if "cas-callback" in href and "ticket=" in href:
                self.ticket_url = href

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False


class EtholClient:
    def __init__(self, email: str, password: str, base_url: str = "https://ethol.pens.ac.id/api"):
        self.email = email
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        })
        self.user_info: Optional[Dict[str, Any]] = None
        self.courses_schema: Dict[int, int] = {}
        self.last_error_detail: str = ""

    def _classify_http_error(self, status_code: int, server_name: str = "ETHOL") -> str:
        """Mengidentifikasi status HTTP menjadi pesan error yang mudah dipahami."""
        if status_code == 502:
            return f"🔴 Server {server_name} Mengalami Gangguan (HTTP 502 Bad Gateway)"
        elif status_code == 503:
            return f"🔴 Server {server_name} Sedang Maintenance / Overload (HTTP 503 Service Unavailable)"
        elif status_code == 504:
            return f"🔴 Server {server_name} Gateway Timeout (HTTP 504 Gateway Timeout)"
        elif status_code == 500:
            return f"🔴 Server {server_name} Terjadi Kesalahan Internal (HTTP 500 Internal Server Error)"
        elif status_code == 403:
            return f"🚫 Akses ke Server {server_name} Ditolak (HTTP 403 Forbidden)"
        elif status_code == 404:
            return f"⚠️ Endpoint Server {server_name} Tidak Ditemukan (HTTP 404 Not Found)"
        else:
            return f"⚠️ Respon Error dari Server {server_name} (HTTP {status_code})"

    def login(self) -> bool:
        """Melakukan login SSO CAS PENS ke ETHOL dengan deteksi error spesifik (Bad Gateway, CAS Down, Kredensial Salah, dsb)."""
        logger.info("Memulai proses login SSO CAS PENS untuk %s...", self.email)
        try:
            cas_redirect_url = f"{self.base_url}/auth/cas-redirect"
            try:
                res_redirect = self.session.get(cas_redirect_url, allow_redirects=True, timeout=15)
            except requests.exceptions.ConnectTimeout:
                self.last_error_detail = "🔴 Server ETHOL RTO / Connection Timeout (Server Kampus Down / Jaringan Terputus)"
                logger.error(self.last_error_detail)
                return False
            except requests.exceptions.ReadTimeout:
                self.last_error_detail = "🔴 Server ETHOL Read Timeout (Server Tidak Merespon Permintaan)"
                logger.error(self.last_error_detail)
                return False
            except requests.exceptions.ConnectionError:
                self.last_error_detail = "🔴 Gagal Terhubung ke Server ETHOL (Koneksi Ditolak / Server ETHOL Down)"
                logger.error(self.last_error_detail)
                return False

            if res_redirect.status_code >= 500:
                self.last_error_detail = self._classify_http_error(res_redirect.status_code, "ETHOL")
                logger.error("Gagal cas-redirect: %s", self.last_error_detail)
                return False

            # Jika sudah otomatis redirect ke callback atau token sudah didapat
            if self.is_logged_in():
                logger.info("Sesi ETHOL masih aktif atau otomatis terautentikasi.")
                self.last_error_detail = "🟢 Sesi Aktif"
                self.refresh_enrolled_courses_schema()
                return True

            # 1. Cek apakah ada link ticket callback CAS (ketika CAS session masih aktif tapi token ETHOL expired)
            ticket_match = re.search(r'href=[\'"]([^\'"]*cas-callback\?ticket=[^\'"]*)[\'"]', res_redirect.text)
            if ticket_match:
                ticket_url = ticket_match.group(1)
                full_ticket_url = urllib.parse.urljoin(res_redirect.url, ticket_url)
                logger.info("Menemukan CAS ticket callback aktif, memvalidasi ticket...")
                try:
                    res_ticket = self.session.get(full_ticket_url, allow_redirects=True, timeout=15)
                    if res_ticket.status_code >= 500:
                        self.last_error_detail = self._classify_http_error(res_ticket.status_code, "ETHOL Callback")
                        return False
                except Exception as e:
                    logger.warning("Gagal validasi tiket CAS: %s", e)

                if self.is_logged_in():
                    logger.info("Login ulang ETHOL berhasil melalui tiket CAS aktif!")
                    self.last_error_detail = "🟢 Sesi Aktif"
                    self.refresh_enrolled_courses_schema()
                    return True

            # 2. Parse form login CAS
            parser = CasFormParser()
            parser.feed(res_redirect.text)

            if not parser.action:
                # Jika form tidak ditemukan, coba bersihkan cookies session yang mungkin corrupt dan minta halaman baru
                logger.warning("Form login CAS tidak ditemukan. Membersihkan cookies dan mencoba ulang...")
                self.session.cookies.clear()
                try:
                    res_redirect = self.session.get(cas_redirect_url, allow_redirects=True, timeout=15)
                    if res_redirect.status_code >= 500:
                        self.last_error_detail = self._classify_http_error(res_redirect.status_code, "ETHOL")
                        return False
                except Exception as e:
                    self.last_error_detail = f"🔴 Gagal Menghubungi ETHOL saat Refresh Sesi ({e})"
                    return False

                parser = CasFormParser()
                parser.feed(res_redirect.text)

            if not parser.action:
                if "cas.pens.ac.id" in res_redirect.url:
                    self.last_error_detail = "⚠️ Halaman SSO CAS PENS Tidak Merespon Form Login (Server SSO mungkin sedang maintenance)"
                else:
                    self.last_error_detail = f"🔴 Gagal Menemukan Halaman SSO CAS PENS (URL: {res_redirect.url})"
                logger.error(self.last_error_detail)
                return False

            action_url = urllib.parse.urljoin(res_redirect.url, parser.action)

            # 3. Siapkan payload kredensial
            payload = dict(parser.inputs)
            payload["username"] = self.email
            payload["password"] = self.password
            payload["_eventId"] = "submit"
            payload["submit"] = "LOGIN"

            # 4. POST login form ke CAS
            logger.info("Mengirimkan kredensial login ke CAS SSO PENS...")
            try:
                login_res = self.session.post(action_url, data=payload, allow_redirects=True, timeout=20)
            except requests.exceptions.Timeout:
                self.last_error_detail = "🔴 Koneksi ke Server SSO CAS PENS Timeout saat Mengirim Kredensial"
                logger.error(self.last_error_detail)
                return False
            except requests.exceptions.ConnectionError:
                self.last_error_detail = "🔴 Gagal Terhubung ke Server SSO CAS PENS (cas.pens.ac.id Offline)"
                logger.error(self.last_error_detail)
                return False

            if login_res.status_code >= 500:
                self.last_error_detail = self._classify_http_error(login_res.status_code, "SSO CAS PENS")
                logger.error(self.last_error_detail)
                return False

            # 5. Validasi apakah sesi login berhasil
            if self.is_logged_in():
                logger.info("Login SSO ETHOL berhasil! Akun: %s (ID: %s)", 
                            self.user_info.get("nama"), self.user_info.get("nomor"))
                self.last_error_detail = "🟢 Sesi Aktif"
                self.refresh_enrolled_courses_schema()
                return True

            # Analisis mengapa login gagal setelah submit kredensial
            resp_text = login_res.text.lower()
            if "tidak cocok" in resp_text or "cannot be determined" in resp_text or "invalid credentials" in resp_text or "salah" in resp_text:
                self.last_error_detail = "❌ Kredensial SSO Salah (Email / Password SSO di .env tidak valid)"
            elif "cas.pens.ac.id" in login_res.url:
                self.last_error_detail = "❌ Kredensial SSO Salah atau Ditolak oleh Server CAS PENS (Pastikan Akun SSO Benar)"
            elif login_res.status_code >= 400:
                self.last_error_detail = self._classify_http_error(login_res.status_code, "ETHOL")
            else:
                self.last_error_detail = "⚠️ Autentikasi ETHOL Gagal (Token sesi tidak diterbitkan oleh server)"

            logger.error("Login CAS gagal. Detail: %s (URL: %s)", self.last_error_detail, login_res.url)
            return False
        except Exception as e:
            self.last_error_detail = f"⚠️ Kesalahan Tak Terduga saat Login: {str(e)}"
            logger.exception(self.last_error_detail)
            return False

    def is_logged_in(self) -> bool:
        """Mengecek apakah sesi aktif dan valid."""
        try:
            res = self.session.get(f"{self.base_url}/auth/validasi-token", timeout=10)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and data.get("nomor"):
                    self.user_info = data
                    return True
            elif res.status_code >= 500:
                self.last_error_detail = self._classify_http_error(res.status_code, "ETHOL")
            return False
        except requests.exceptions.Timeout:
            self.last_error_detail = "🔴 Server ETHOL RTO / Connection Timeout"
            return False
        except requests.exceptions.ConnectionError:
            self.last_error_detail = "🔴 Gagal Terhubung ke Server ETHOL (Server Down / Offline)"
            return False
        except Exception:
            return False

    def ensure_authenticated(self) -> bool:
        """Pastikan selalu dalam kondisi terautentikasi (auto re-login jika token expired)."""
        if self.is_logged_in():
            return True
        logger.warning("Sesi ETHOL telah kedaluwarsa. Melakukan login ulang...")
        return self.login()

    def get_notifications(self, filter_notif: str = "SEMUA") -> List[Dict[str, Any]]:
        """Mengambil daftar notifikasi terbaru mahasiswa."""
        if not self.ensure_authenticated():
            return []

        try:
            res = self.session.get(
                f"{self.base_url}/notifikasi/mahasiswa",
                params={"filterNotif": filter_notif},
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                return data if isinstance(data, list) else []
            logger.warning("Gagal fetch notifikasi, status: %s", res.status_code)
            return []
        except Exception as e:
            logger.error("Error get_notifications: %s", e)
            return []

    def mark_notification_as_read(self, id_notifikasi: int) -> bool:
        """Menandai notifikasi sebagai sudah dibaca."""
        try:
            res = self.session.put(
                f"{self.base_url}/notifikasi/mahasiswa-baca-notif",
                json={"idNotifikasi": id_notifikasi},
                timeout=10
            )
            return res.status_code == 200
        except Exception:
            return False

    def refresh_enrolled_courses_schema(self):
        """Memuat daftar schema untuk setiap mata kuliah yang diambil mahasiswa."""
        try:
            courses = self.get_enrolled_courses()
            for c in courses:
                kid = c.get("nomor")
                schema = c.get("jenisSchema") or c.get("jenis_schema") or 4
                if kid:
                    self.courses_schema[kid] = int(schema)
            logger.info("Berhasil memetakan %s skema mata kuliah mahasiswa.", len(self.courses_schema))
        except Exception as e:
            logger.warning("Gagal refresh schema matakuliah: %s", e)

    def get_schema_for_kuliah(self, kuliah_id: int, fallback: int = 4) -> int:
        """Mengambil jenis schema kuliah (D3=1, Terapan/STr=4, dsb)."""
        if not self.courses_schema:
            self.refresh_enrolled_courses_schema()
        return self.courses_schema.get(kuliah_id, fallback)

    def get_kuliah_detail(self, kuliah_id: int, jenis_schema: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Mengambil detail mata kuliah dan data dosen."""
        if not self.ensure_authenticated():
            return None

        if jenis_schema is None:
            jenis_schema = self.get_schema_for_kuliah(kuliah_id)

        try:
            res = self.session.get(
                f"{self.base_url}/kuliah/by-kuliah-js",
                params={"kuliah": kuliah_id, "jenisSchema": jenis_schema},
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
            # Coba fallback ke schema alternatif jika kosong
            alt_schema = 1 if jenis_schema != 1 else 4
            res_alt = self.session.get(
                f"{self.base_url}/kuliah/by-kuliah-js",
                params={"kuliah": kuliah_id, "jenisSchema": alt_schema},
                timeout=10
            )
            if res_alt.status_code == 200:
                data = res_alt.json()
                if isinstance(data, list) and len(data) > 0:
                    self.courses_schema[kuliah_id] = alt_schema
                    return data[0]
            return None
        except Exception as e:
            logger.error("Error get_kuliah_detail: %s", e)
            return None

    def get_active_presensi(self, kuliah_id: int, jenis_schema: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Mengambil sesi presensi aktif untuk matakuliah terkait.
        Sesi yang aktif memiliki field 'open' bernilai 1.
        """
        if not self.ensure_authenticated():
            return None

        if jenis_schema is None:
            jenis_schema = self.get_schema_for_kuliah(kuliah_id)

        try:
            res = self.session.get(
                f"{self.base_url}/presensi/aktif-kuliah",
                params={"kuliah": kuliah_id, "jenis_schema": jenis_schema},
                timeout=10
            )
            # Jika 403 / akses ditolak karena salah schema, coba schema alternatif
            if res.status_code == 403 or (res.status_code == 200 and isinstance(res.json(), dict) and not res.json().get("sukses", True)):
                alt_schema = 1 if jenis_schema != 1 else 4
                logger.info("Mencoba ulang get_active_presensi untuk kuliah %s dengan schema %s", kuliah_id, alt_schema)
                res_alt = self.session.get(
                    f"{self.base_url}/presensi/aktif-kuliah",
                    params={"kuliah": kuliah_id, "jenis_schema": alt_schema},
                    timeout=10
                )
                if res_alt.status_code == 200:
                    res = res_alt
                    jenis_schema = alt_schema
                    self.courses_schema[kuliah_id] = alt_schema

            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    for item in data:
                        if item.get("open") == 1 or item.get("open") is True:
                            item["jenisSchema"] = item.get("jenisSchema") or jenis_schema
                            return item
            return None
        except Exception as e:
            logger.error("Error get_active_presensi: %s", e)
            return None

    def get_riwayat_presensi(self, kuliah_id: int, jenis_schema: Optional[int] = None) -> List[Dict[str, Any]]:
        """Mengambil riwayat presensi saya untuk matakuliah tersebut."""
        if not self.ensure_authenticated() or not self.user_info:
            return []

        if jenis_schema is None:
            jenis_schema = self.get_schema_for_kuliah(kuliah_id)

        try:
            mahasiswa_id = self.user_info.get("nomor")
            res = self.session.get(
                f"{self.base_url}/presensi/riwayat",
                params={"kuliah": kuliah_id, "jenis_schema": jenis_schema, "mahasiswa": mahasiswa_id},
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                return data if isinstance(data, list) else []
            return []
        except Exception as e:
            logger.error("Error get_riwayat_presensi: %s", e)
            return []

    def submit_presensi(
        self,
        kuliah_id: int,
        key: Any,
        jenis_schema: Optional[int] = None,
        kuliah_asal: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Mengirim payload presensi untuk mahasiswa saat ini.
        Payload: { kuliah, jenis_schema, mahasiswa, key, kuliah_asal }
        """
        if not self.ensure_authenticated() or not self.user_info:
            return {"sukses": False, "pesan": "Tidak terautentikasi"}

        if jenis_schema is None:
            jenis_schema = self.get_schema_for_kuliah(kuliah_id)

        if kuliah_asal is None:
            kuliah_asal = kuliah_id

        try:
            mahasiswa_id = self.user_info.get("nomor")
            payload = {
                "kuliah": kuliah_id,
                "jenis_schema": jenis_schema,
                "mahasiswa": mahasiswa_id,
                "key": key,
                "kuliah_asal": kuliah_asal
            }
            logger.info("Mengirim payload presensi: %s", payload)
            res = self.session.post(
                f"{self.base_url}/presensi/mahasiswa",
                json=payload,
                timeout=15
            )
            if res.status_code == 200:
                return res.json()
            return {"sukses": False, "pesan": f"HTTP {res.status_code}: {res.text}"}
        except Exception as e:
            logger.exception("Error submit_presensi: %s", e)
            return {"sukses": False, "pesan": str(e)}

    def get_system_config(self) -> Optional[Dict[str, Any]]:
        """Mengambil konfigurasi tahun ajaran dan semester aktif dari ETHOL."""
        if not self.ensure_authenticated():
            return None
        try:
            res = self.session.get(f"{self.base_url}/auth/config", timeout=10)
            if res.status_code == 200:
                return res.json()
            return None
        except Exception as e:
            logger.error("Error get_system_config: %s", e)
            return None

    def get_enrolled_courses(self) -> List[Dict[str, Any]]:
        """Mengambil daftar seluruh mata kuliah mahasiswa di semester aktif."""
        cfg = self.get_system_config()
        if not cfg:
            return []
        tahun = cfg.get("tahun_aktif")
        semester = cfg.get("semester_aktif")
        if not tahun or not semester:
            return []

        try:
            res = self.session.get(
                f"{self.base_url}/kuliah",
                params={"tahun": tahun, "semester": semester},
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                return data if isinstance(data, list) else []
            return []
        except Exception as e:
            logger.error("Error get_enrolled_courses: %s", e)
            return []

    def get_student_stats(self) -> Optional[Dict[str, Any]]:
        """Mengambil data statistik kehadiran dan ringkasan semester dari ETHOL."""
        if not self.ensure_authenticated():
            return None
        cfg = self.get_system_config()
        if not cfg:
            return None
        tahun = cfg.get("tahun_aktif")
        semester = cfg.get("semester_aktif")
        if not tahun or not semester:
            return None

        try:
            res = self.session.get(
                f"{self.base_url}/presensi/stat-beranda-mahasiswa",
                params={"tahun": tahun, "semester": semester},
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and data.get("sukses"):
                    return data.get("data")
            return None
        except Exception as e:
            logger.error("Error get_student_stats: %s", e)
            return None

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """
        Mengambil daftar seluruh tugas yang BELUM dikumpulkan oleh mahasiswa.
        Mengembalikan list tugas dengan detail matakuliah, judul, dan tenggat deadline.
        """
        if not self.ensure_authenticated():
            logger.warning("get_pending_tasks dibatalkan karena sesi ETHOL tidak valid.")
            return []

        courses = self.get_enrolled_courses()
        if not courses:
            logger.warning("get_pending_tasks: gagal mengambil daftar kuliah dari ETHOL. Data kosong atau sesi expired.")
            return []

        pending_tasks = []
        logger.info("Mendapatkan daftar tugas dari %s kuliah aktif.", len(courses))

        for c in courses:
            kuliah_id = c.get("nomor")
            jenis_schema = c.get("jenisSchema", 1)
            mk_name = (
                c.get("matakuliah", {}).get("nama")
                or c.get("nama")
                or c.get("nama_matakuliah")
                or f"Matakuliah #{kuliah_id}"
            )
            dosen_name = c.get("dosen") or c.get("nama_dosen") or "Dosen Pengampu"

            try:
                res = self.session.get(
                    f"{self.base_url}/tugas",
                    params={"kuliah": kuliah_id, "jenisSchema": jenis_schema},
                    timeout=10
                )
                if res.status_code != 200:
                    continue

                tasks = res.json()
                if not isinstance(tasks, list):
                    continue

                # Deduplikasi tugas berdasarkan ID tugas
                unique_pending = {}
                for t in tasks:
                    tid = t.get("nomor") or t.get("id_tugas") or t.get("id")
                    if not tid:
                        continue
                    sudah_kumpul = bool(t.get("nomor_tugas_mahasiswa") or t.get("submission_time"))
                    if not sudah_kumpul and tid not in unique_pending:
                        unique_pending[tid] = {
                            "id_tugas": tid,
                            "judul": t.get("title") or t.get("judul") or "Tugas",
                            "deskripsi": t.get("deskripsi") or "",
                            "matakuliah": mk_name,
                            "dosen": dosen_name,
                            "deadline": t.get("deadline") or t.get("tgl_deadline") or t.get("tglDeadline") or "Tidak ditentukan",
                            "tutup": t.get("tutup", 0),
                            "created": t.get("created") or ""
                        }
                pending_tasks.extend(unique_pending.values())
            except Exception as e:
                logger.error("Error get_pending_tasks for kuliah %s: %s", kuliah_id, e)

        return pending_tasks

    def get_tasks_for_course(self, kuliah_id: int, jenis_schema: Optional[int] = None) -> List[Dict[str, Any]]:
        """Mengambil seluruh daftar tugas untuk mata kuliah tertentu dengan deduplikasi riwayat."""
        if not self.ensure_authenticated():
            return []

        if jenis_schema is None:
            jenis_schema = self.get_schema_for_kuliah(kuliah_id)

        try:
            res = self.session.get(
                f"{self.base_url}/tugas",
                params={"kuliah": kuliah_id, "jenisSchema": jenis_schema},
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    unique_tasks = {}
                    for t in data:
                        tid = t.get("id") or t.get("nomor") or t.get("id_tugas")
                        if not tid:
                            continue
                        if tid not in unique_tasks:
                            unique_tasks[tid] = t
                        else:
                            # Jika ada duplikasi data join di server ETHOL, ambil yang memiliki record pengumpulan terbaru
                            existing = unique_tasks[tid]
                            curr_sub = t.get("nomor_tugas_mahasiswa") or 0
                            exist_sub = existing.get("nomor_tugas_mahasiswa") or 0
                            if curr_sub >= exist_sub:
                                unique_tasks[tid] = t
                    return list(unique_tasks.values())
            return []
        except Exception as e:
            logger.error("Error get_tasks_for_course %s: %s", kuliah_id, e)
            return []

    def submit_task_file(
        self,
        id_tugas: int,
        file_name: str,
        file_bytes: bytes,
        nomor_tugas_mahasiswa: Optional[int] = None,
        nomor_tugas_file_mahasiswa: Optional[int] = None,
        catatan: str = ""
    ) -> Dict[str, Any]:
        """
        Mengunggah atau memperbarui file jawaban tugas mahasiswa ke ETHOL.
        - Jika tugas baru (belum pernah dikumpulkan): POST /tugas/submit
        - Jika tugas sudah pernah dikumpulkan (ubah file): PUT /tugas/submit
        """
        if not self.ensure_authenticated():
            return {"sukses": False, "pesan": "Tidak terautentikasi ke ETHOL"}

        try:
            url = f"{self.base_url}/tugas/submit"
            data_payload = {
                "id_tugas": str(id_tugas),
                "catatan": catatan
            }
            files = {
                "file": (file_name, file_bytes)
            }
            
            is_update = bool(nomor_tugas_mahasiswa and nomor_tugas_file_mahasiswa)
            if is_update:
                data_payload["nomor_tugas_mahasiswa"] = str(nomor_tugas_mahasiswa)
                data_payload["nomor_tugas_file_mahasiswa"] = str(nomor_tugas_file_mahasiswa)
                logger.info(
                    "Memperbarui (PUT) file tugas '%s' untuk tugas #%s (sub_id: %s, file_id: %s) ke ETHOL...",
                    file_name, id_tugas, nomor_tugas_mahasiswa, nomor_tugas_file_mahasiswa
                )
                res = self.session.put(url, data=data_payload, files=files, timeout=60)
            else:
                logger.info("Mengunggah baru (POST) file tugas '%s' untuk tugas #%s ke ETHOL...", file_name, id_tugas)
                res = self.session.post(url, data=data_payload, files=files, timeout=60)

            if 200 <= res.status_code < 300:
                try:
                    resp_json = res.json()
                    if isinstance(resp_json, dict):
                        return resp_json
                    return {"sukses": True, "pesan": "Berhasil disimpan"}
                except Exception:
                    return {"sukses": True, "pesan": "Berhasil disimpan"}

            logger.error("Gagal submit tugas: HTTP %s - %s", res.status_code, res.text)
            return {"sukses": False, "pesan": f"HTTP {res.status_code}: {res.text}"}
        except Exception as e:
            logger.exception("Exception submit_task_file: %s", e)
            return {"sukses": False, "pesan": str(e)}

    def get_student_schedule(self) -> List[Dict[str, Any]]:
        """
        Mengambil daftar jadwal perkuliahan mahasiswa untuk semester aktif.
        """
        if not self.ensure_authenticated():
            return []

        cfg = self.get_system_config() or {}
        tahun = cfg.get("tahun_aktif")
        semester = cfg.get("semester_aktif")
        if not tahun or not semester:
            return []

        try:
            res = self.session.get(
                f"{self.base_url}/jadwal/jadwal-online",
                params={"tahun": tahun, "semester": semester},
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    enrolled = self.get_enrolled_courses()
                    enrolled_names = {
                        str(c.get("matakuliah", {}).get("nama") or c.get("nama") or "").lower().strip()
                        for c in enrolled
                    }
                    enrolled_codes = {
                        str(c.get("kode_kelas") or "").lower().strip()
                        for c in enrolled if c.get("kode_kelas")
                    }

                    my_schedule = []
                    for item in data:
                        mk = str(item.get("matakuliah") or item.get("nama") or item.get("mata_kuliah") or "").lower().strip()
                        kk = str(item.get("kode_kelas") or "").lower().strip()
                        if (enrolled_names and mk in enrolled_names) or (enrolled_codes and kk in enrolled_codes):
                            # Format jam
                            jam_awal = item.get("jam_awal")
                            jam_akhir = item.get("jam_akhir")
                            if jam_awal and jam_akhir:
                                item["jam"] = f"{jam_awal} - {jam_akhir} WIB"
                            elif jam_awal:
                                item["jam"] = f"{jam_awal} WIB"
                            elif not item.get("jam"):
                                item["jam"] = "Sesuai Jadwal ETHOL"

                            # Format nama dosen lengkap dengan gelar
                            dosen_raw = str(item.get("dosen") or "").strip()
                            g_dpn = str(item.get("gelar_dpn") or "").strip()
                            g_blk = str(item.get("gelar_blk") or "").strip()
                            parts = []
                            if g_dpn:
                                parts.append(g_dpn)
                            if dosen_raw:
                                parts.append(dosen_raw)
                            full_dosen = " ".join(parts).strip()
                            if g_blk:
                                full_dosen = f"{full_dosen}, {g_blk}".strip() if full_dosen else g_blk
                            item["dosen_lengkap"] = full_dosen or dosen_raw or "-"

                            my_schedule.append(item)

                    if my_schedule:
                        return my_schedule
                    return data
            
            # Fallback: jika jadwal spesifik jam belum diatur admin di endpoint jadwal, susun dari mata kuliah aktif
            courses = self.get_enrolled_courses()
            fallback_schedule = []
            for c in courses:
                dosen_raw = str(c.get("dosen") or "").strip()
                g_dpn = str(c.get("gelar_dpn") or "").strip()
                g_blk = str(c.get("gelar_blk") or "").strip()
                parts = []
                if g_dpn:
                    parts.append(g_dpn)
                if dosen_raw:
                    parts.append(dosen_raw)
                full_dosen = " ".join(parts).strip()
                if g_blk:
                    full_dosen = f"{full_dosen}, {g_blk}".strip() if full_dosen else g_blk

                fallback_schedule.append({
                    "matakuliah": c.get("matakuliah", {}).get("nama") or c.get("nama") or f"Matakuliah #{c.get('nomor')}",
                    "dosen": full_dosen or dosen_raw or "-",
                    "dosen_lengkap": full_dosen or dosen_raw or "-",
                    "kode_kelas": c.get("kode_kelas", "-"),
                    "pararel": c.get("pararel", "-"),
                    "hari": c.get("hari") or "Sesuai Jadwal Semester",
                    "jam": c.get("jam") or "Sesuai Jadwal ETHOL",
                    "ruang": c.get("ruang") or "Online / Lab"
                })
            return fallback_schedule
        except Exception as e:
            logger.error("Error get_student_schedule: %s", e)
            return []

    def get_today_schedule(self) -> List[Dict[str, Any]]:
        """
        Mengambil daftar jadwal perkuliahan khusus untuk HARI INI, diurutkan secara kronologis berdasarkan jam mulai.
        """
        schedule = self.get_student_schedule()
        if not schedule:
            return []

        days_map = {
            0: ["senin", "1"],
            1: ["selasa", "2"],
            2: ["rabu", "3"],
            3: ["kamis", "4"],
            4: ["jumat", "jum'at", "5"],
            5: ["sabtu", "6"],
            6: ["minggu", "ahad", "7"]
        }
        from datetime import datetime
        import pytz
        tz = pytz.timezone("Asia/Jakarta")
        today_idx = datetime.now(tz).weekday()
        today_keywords = days_map.get(today_idx, [])

        today_items = []
        for item in schedule:
            hari_str = str(item.get("hari") or item.get("nama_hari") or "").lower().strip()
            nomor_hari = str(item.get("nomor_hari") or item.get("hari_ke") or "").strip()
            if any(k in hari_str for k in today_keywords) or nomor_hari in today_keywords:
                today_items.append(item)

        # Urutkan berdasarkan jam_awal secara kronologis
        today_items.sort(key=lambda x: str(x.get("jam_awal") or "99:99"))

        return today_items

    def get_course_materials(self, kuliah_id: int, jenis_schema: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Mengambil daftar seluruh materi perkuliahan untuk suatu mata kuliah.
        Mendukung deduplikasi dan pemetaan tipe file/link.
        """
        if not self.ensure_authenticated():
            return []

        if jenis_schema is None:
            jenis_schema = self.get_schema_for_kuliah(kuliah_id)

        try:
            res = self.session.get(
                f"{self.base_url}/materi",
                params={"matakuliah": kuliah_id, "jenis_schema": jenis_schema},
                timeout=15
            )
            # Coba fallback schema jika 403
            if res.status_code == 403 or (res.status_code == 200 and isinstance(res.json(), dict) and not res.json().get("sukses", True)):
                alt_schema = 1 if jenis_schema != 1 else 4
                res_alt = self.session.get(
                    f"{self.base_url}/materi",
                    params={"matakuliah": kuliah_id, "jenis_schema": alt_schema},
                    timeout=15
                )
                if res_alt.status_code == 200 and isinstance(res_alt.json(), list):
                    res = res_alt
                    self.courses_schema[kuliah_id] = alt_schema

            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    # Sort materi berdasarkan ID atau created secara ascending (Pertemuan 1, 2, dst)
                    data.sort(key=lambda x: x.get("id") or 0)
                    return data
            logger.warning("Gagal fetch materi untuk kuliah %s, status: %s", kuliah_id, res.status_code)
            return []
        except Exception as e:
            logger.error("Error get_course_materials for kuliah %s: %s", kuliah_id, e)
            return []

    def download_material_file(self, file_url: str) -> Optional[Tuple[str, bytes]]:
        """
        Mengunduh file materi dari server ETHOL.
        Mengembalikan (nama_file, file_bytes).
        """
        if not self.ensure_authenticated():
            return None

        try:
            clean_url = file_url.strip()
            logger.info("Mengunduh file materi dari URL: %s", clean_url)
            res = self.session.get(clean_url, timeout=60)
            if res.status_code == 200:
                path_part = urllib.parse.urlparse(clean_url).path
                file_name = urllib.parse.unquote(path_part.split("/")[-1])
                # Bersihkan timestamp jika ada, atau pastikan ekstensi ada
                if not file_name:
                    file_name = "materi_kuliah.pdf"
                return file_name, res.content
            logger.error("Gagal download materi: HTTP %s", res.status_code)
            return None
        except Exception as e:
            logger.exception("Exception download_material_file: %s", e)
            return None


