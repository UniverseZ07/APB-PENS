import os
import subprocess
import shutil
import re
import time
import requests
from datetime import timedelta
from typing import List, Dict, Any


def get_network_interfaces() -> List[Dict[str, Any]]:
    """Mengambil daftar seluruh interface jaringan dan alamat IP di Ubuntu VM."""
    try:
        res = subprocess.run(["ip", "-brief", "addr"], capture_output=True, text=True, timeout=5)
        interfaces = []
        for line in res.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                iface = parts[0]
                status = parts[1]
                ips = parts[2:] if len(parts) > 2 else []
                ipv4_list = [ip.split("/")[0] for ip in ips if "." in ip]
                interfaces.append({
                    "name": iface,
                    "status": status,
                    "ips": ipv4_list
                })
        return interfaces
    except Exception:
        return []


def test_connection() -> List[Dict[str, Any]]:
    """Menguji konektivitas VM ke internet, ETHOL, dan Telegram API."""
    targets = [
        {"name": "ETHOL PENS", "host": "ethol.pens.ac.id", "url": "https://ethol.pens.ac.id"},
        {"name": "Telegram API", "host": "api.telegram.org", "url": "https://api.telegram.org"},
        {"name": "Internet / Google", "host": "google.com", "url": "https://www.google.com"},
        {"name": "Cloudflare DNS", "host": "1.1.1.1", "url": "https://1.1.1.1"}
    ]

    results = []
    for t in targets:
        name = t["name"]
        host = t["host"]
        url = t["url"]

        # 1. Coba ICMP Ping
        ping_ok = False
        ping_latency = None
        try:
            res_ping = subprocess.run(["ping", "-c", "1", "-W", "1", host], capture_output=True, text=True, timeout=3)
            if res_ping.returncode == 0:
                m = re.search(r"time=([\d\.]+)\s*ms", res_ping.stdout)
                ping_latency = f"{m.group(1)} ms" if m else "OK"
                ping_ok = True
        except Exception:
            pass

        if ping_ok:
            results.append({
                "name": name,
                "host": host,
                "status": "🟢 Terhubung",
                "latency": ping_latency,
                "method": "ICMP"
            })
            continue

        # 2. Jika ICMP diblokir firewall, uji via HTTP/TCP
        try:
            t0 = time.time()
            r = requests.get(url, timeout=3)
            t_ms = (time.time() - t0) * 1000
            if r.status_code < 500:
                results.append({
                    "name": name,
                    "host": host,
                    "status": "🟢 Terhubung",
                    "latency": f"{t_ms:.1f} ms",
                    "method": "HTTP"
                })
            else:
                results.append({
                    "name": name,
                    "host": host,
                    "status": "🔴 Gagal (HTTP Error)",
                    "latency": "-",
                    "method": "HTTP"
                })
        except Exception:
            results.append({
                "name": name,
                "host": host,
                "status": "🔴 Terputus (RTO)",
                "latency": "-",
                "method": "FAIL"
            })

    return results


def get_system_resources() -> Dict[str, Any]:
    """Mengambil informasi penggunaan Memory (RAM), Disk, dan Uptime VM."""
    # Memory
    mem_total = 0
    mem_available = 0
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1]) * 1024
        mem_used = mem_total - mem_available
        mem_percent = (mem_used / mem_total * 100) if mem_total else 0
    except Exception:
        mem_total = 1
        mem_used = 0
        mem_percent = 0

    # Disk
    try:
        disk = shutil.disk_usage("/")
        disk_percent = (disk.used / disk.total * 100) if disk.total else 0
        disk_total_gb = disk.total / (1024**3)
        disk_used_gb = disk.used / (1024**3)
    except Exception:
        disk_total_gb = 0
        disk_used_gb = 0
        disk_percent = 0

    # Uptime
    try:
        with open("/proc/uptime", "r") as f:
            uptime_sec = float(f.readline().split()[0])
        days = int(uptime_sec // 86400)
        hours = int((uptime_sec % 86400) // 3600)
        mins = int((uptime_sec % 3600) // 60)
        if days > 0:
            uptime_str = f"{days} hari {hours} jam {mins} mnt"
        else:
            uptime_str = f"{hours} jam {mins} menit"
    except Exception:
        uptime_str = "-"

    return {
        "mem_total_gb": mem_total / (1024**3),
        "mem_used_gb": mem_used / (1024**3),
        "mem_percent": mem_percent,
        "disk_total_gb": disk_total_gb,
        "disk_used_gb": disk_used_gb,
        "disk_percent": disk_percent,
        "uptime": uptime_str
    }


def reboot_vm() -> bool:
    """Menjalankan reboot VM via sudo."""
    try:
        subprocess.Popen(["sudo", "reboot"])
        return True
    except Exception:
        return False
