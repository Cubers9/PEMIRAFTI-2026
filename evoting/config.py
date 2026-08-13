"""
Konfigurasi terpusat — dibaca dari environment (.env).

Modul ini SENGAJA tidak mengimpor apa pun dari dalam package (mis. `core`)
agar bebas dari circular import; ia hanya menyediakan konstanta yang boleh
diimpor oleh modul mana pun (termasuk `blockchain`).

Semua path folder di-anchor absolut ke root project sehingga konsisten apa pun
current working directory saat gunicorn dijalankan di VPS.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# Root project = satu tingkat di atas package `evoting/`.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

# --- Keamanan & anonimitas ------------------------------------------------- #
SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32)
SECRET_SALT = os.environ.get("SECRET_SALT", "BEM_FTI_GND_2024_SECURE_SALT")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# --- Pasangan calon --------------------------------------------------------- #
CANDIDATES = ["Paslon 01", "Paslon 02"]

# --- Folder runtime (absolut) ---------------------------------------------- #
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloads")
BACKUP_FOLDER = os.path.join(BASE_DIR, "backups")

# --- Database --------------------------------------------------------------- #
SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URI", "sqlite:///evoting.db")

# --- Batas unggahan --------------------------------------------------------- #
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

# --- Verifikasi KRS via QR -------------------------------------------------- #
KRS_ALLOWED_DOMAINS = [
    d.strip().lower()
    for d in os.environ.get("KRS_ALLOWED_DOMAINS", "gunadarma.ac.id").split(",")
    if d.strip()
]
KRS_DOWNLOAD_TIMEOUT = int(os.environ.get("KRS_DOWNLOAD_TIMEOUT", "10"))
KRS_MAX_DOWNLOAD_MB = int(os.environ.get("KRS_MAX_DOWNLOAD_MB", "10"))
# Opsional: folder KRS lokal untuk fallback/pengujian saat unduh live gagal.
# Kosongkan di produksi.
KRS_LOCAL_FALLBACK_DIR = os.environ.get("KRS_LOCAL_FALLBACK_DIR", "").strip()
