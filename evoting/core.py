import os
from datetime import datetime
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from evoting import config
from evoting.config import (
    SECRET_SALT, CANDIDATES,
    KRS_ALLOWED_DOMAINS, KRS_DOWNLOAD_TIMEOUT, KRS_MAX_DOWNLOAD_MB,
    KRS_LOCAL_FALLBACK_DIR,
)
from evoting.blockchain import Blockchain
from evoting.engines.ocr import OCREngine
from evoting.engines.qr import QREngine
from evoting.engines.krs_verifier import KRSVerifier

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['DOWNLOAD_FOLDER'] = config.DOWNLOAD_FOLDER   # KRS asli hasil unduhan (sementara)
app.config['BACKUP_FOLDER'] = config.BACKUP_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

for _folder in (app.config['UPLOAD_FOLDER'],
                app.config['DOWNLOAD_FOLDER'],
                app.config['BACKUP_FOLDER']):
    if not os.path.exists(_folder):
        os.makedirs(_folder, exist_ok=True)

db = SQLAlchemy(app)
ocr_engine = OCREngine()
qr_engine = QREngine()
krs_verifier = KRSVerifier(
    ocr_engine=ocr_engine,
    download_folder=app.config['DOWNLOAD_FOLDER'],
    allowed_domains=KRS_ALLOWED_DOMAINS,
    timeout=KRS_DOWNLOAD_TIMEOUT,
    max_mb=KRS_MAX_DOWNLOAD_MB,
)

import json
def backup_blockchain_to_json():
    """Exports the current blockchain to a JSON file for backup."""
    try:
        data = [block.to_dict() for block in blockchain.chain]
        backup_path = os.path.join(app.config['BACKUP_FOLDER'], 'blockchain_backup.json')
        with open(backup_path, 'w') as f:
            json.dump(data, f, indent=4)
        print(f"[+] Backup berhasil dibuat di {backup_path}")
    except Exception as e:
        print(f"[!] Gagal membuat backup: {e}")

class VotingConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    voting_start = db.Column(db.String(30), nullable=True)
    voting_end = db.Column(db.String(30), nullable=True)


def get_voting_window():
    """Returns (start_dt, end_dt) from DB, or (None, None) if not set."""
    try:
        config = VotingConfig.query.first()
        if config and config.voting_start and config.voting_end:
            start = datetime.strptime(config.voting_start, '%Y-%m-%dT%H:%M')
            end = datetime.strptime(config.voting_end, '%Y-%m-%dT%H:%M')
            return start, end
    except Exception:
        pass
    return None, None


def get_voting_status():
    """Returns 'open', 'before', or 'closed'. Returns 'open' if no window is configured."""
    start, end = get_voting_window()
    if start is None or end is None:
        return 'open'
    now = datetime.now()
    if now < start:
        return 'before'
    if now > end:
        return 'closed'
    return 'open'


class VoteBlock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    index = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.String(50), nullable=False)
    npm = db.Column(db.String(64), nullable=False)
    vote = db.Column(db.String(50), nullable=False)
    prev_hash = db.Column(db.String(64), nullable=False)
    hash = db.Column(db.String(64), nullable=False)

class KRSLog(db.Model):
    """Log audit setiap percobaan upload KRS + hasil scan QR (untuk admin)."""
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.String(30))       # waktu upload
    npm = db.Column(db.String(20))             # NPM input pemilih
    name = db.Column(db.String(100))           # Nama input pemilih
    kelas = db.Column(db.String(30))           # Kelas input pemilih
    filename = db.Column(db.String(200))       # nama file KRS terupload (uploads/)
    qr_url = db.Column(db.String(300))         # hasil scan QR (URL) atau kosong
    status = db.Column(db.String(20))          # VALID | GAGAL
    keterangan = db.Column(db.Text)            # detail hasil / alasan gagal


# --- Proteksi brute-force login admin -------------------------------------- #
# Disimpan di DB (bukan memori) agar blokir berlaku lintas proses: server
# pemilih (8000) dan admin (8001) berbagi satu evoting.db, sehingga IP yang
# diblok karena gagal login di admin ikut terkunci di sisi pemilih.

MAX_LOGIN_ATTEMPTS = 5              # gagal berturut sebelum diblokir
BLOCK_DURATION_HOURS = 3           # lama blokir IP


class LoginAttempt(db.Model):
    """Menghitung kegagalan login per-IP dalam jendela waktu berjalan."""
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(64), unique=True, index=True, nullable=False)
    fail_count = db.Column(db.Integer, default=0, nullable=False)
    last_attempt = db.Column(db.DateTime, default=datetime.now)


class IPBlock(db.Model):
    """IP yang sedang diblokir sampai `blocked_until`."""
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(64), unique=True, index=True, nullable=False)
    blocked_until = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(200))


def get_client_ip():
    """IP klien sebenarnya, memperhitungkan reverse proxy (X-Forwarded-For)."""
    from flask import request
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def is_ip_blocked(ip):
    """(blocked: bool, sisa: timedelta|None) untuk IP tertentu."""
    from datetime import timedelta  # noqa: F401  (dipakai lewat operasi datetime)
    with app.app_context():
        rec = IPBlock.query.filter_by(ip=ip).first()
        if not rec:
            return False, None
        now = datetime.now()
        if rec.blocked_until <= now:
            # Masa blokir habis: bersihkan agar bisa mencoba lagi.
            db.session.delete(rec)
            attempt = LoginAttempt.query.filter_by(ip=ip).first()
            if attempt:
                db.session.delete(attempt)
            db.session.commit()
            return False, None
        return True, rec.blocked_until - now


def register_failed_login(ip):
    """Catat 1 kegagalan login. Kembalikan (diblokir_sekarang, sisa_percobaan)."""
    from datetime import timedelta
    with app.app_context():
        attempt = LoginAttempt.query.filter_by(ip=ip).first()
        if not attempt:
            attempt = LoginAttempt(ip=ip, fail_count=0)
            db.session.add(attempt)
        attempt.fail_count += 1
        attempt.last_attempt = datetime.now()

        if attempt.fail_count >= MAX_LOGIN_ATTEMPTS:
            until = datetime.now() + timedelta(hours=BLOCK_DURATION_HOURS)
            block = IPBlock.query.filter_by(ip=ip).first()
            if not block:
                block = IPBlock(ip=ip, blocked_until=until,
                                reason=f'{MAX_LOGIN_ATTEMPTS}x gagal login admin')
                db.session.add(block)
            else:
                block.blocked_until = until
            db.session.commit()
            return True, 0
        db.session.commit()
        return False, MAX_LOGIN_ATTEMPTS - attempt.fail_count


def clear_failed_logins(ip):
    """Reset hitungan kegagalan setelah login sukses."""
    with app.app_context():
        attempt = LoginAttempt.query.filter_by(ip=ip).first()
        if attempt:
            db.session.delete(attempt)
            db.session.commit()

def get_shared_blockchain():
    from evoting.blockchain import Block
    bc = Blockchain()
    with app.app_context():
        try:
            db_blocks = VoteBlock.query.order_by(VoteBlock.index).all()
            if db_blocks:
                bc.chain = []
                for db_b in db_blocks:
                    block = Block(
                        index=db_b.index,
                        npm=db_b.npm,
                        vote=db_b.vote,
                        prev_hash=db_b.prev_hash,
                        timestamp=float(db_b.timestamp)
                    )
                    block.hash = db_b.hash
                    bc.chain.append(block)
        except Exception as e:
            print(f"Blockchain load warning: {e}")
    return bc

def reload_blockchain():
    """Reloads the blockchain from the database to stay in sync."""
    new_bc = get_shared_blockchain()
    # Update in-place to preserve object reference in other modules
    blockchain.chain = new_bc.chain
    return blockchain

blockchain = get_shared_blockchain()

def sync_blockchain_to_db():
    """Persist any in-memory blocks that are not yet in the database."""
    for block in blockchain.chain:
        exists = VoteBlock.query.filter_by(index=block.index).first()
        if not exists:
            b = VoteBlock(
                index=block.index,
                timestamp=str(block.timestamp),
                npm=block.npm,
                vote=block.vote,
                prev_hash=block.prev_hash,
                hash=block.hash
            )
            db.session.add(b)
    db.session.commit()

def init_db():
    with app.app_context():
        # Tabel: VoteBlock (ledger), VotingConfig (jadwal), KRSLog (audit),
        # LoginAttempt & IPBlock (proteksi brute-force).
        #
        # Kedua server (pemilih 8000 & admin 8001) berbagi satu SQLite dan
        # sering dijalankan bersamaan (mis. docker-compose). Pada DB baru,
        # keduanya bisa berlomba menjalankan create_all() sehingga salah satu
        # gagal dengan "table ... already exists". Itu tidak berbahaya —
        # tabelnya memang sudah ada — jadi kita telan galat spesifik ini.
        from sqlalchemy.exc import OperationalError
        try:
            db.create_all()
        except OperationalError as e:
            if "already exists" not in str(e).lower():
                raise
            db.session.rollback()
        # Initial sync for genesis block
        try:
            sync_blockchain_to_db()
        except OperationalError:
            # Server lain sedang menulis genesis block pada DB baru — abaikan,
            # blok akan tersinkron pada permintaan berikutnya via reload.
            db.session.rollback()


def _format_sisa(delta):
    """Ubah timedelta jadi teks 'X jam Y menit' untuk halaman blokir."""
    total_menit = int(delta.total_seconds() // 60)
    jam, menit = divmod(total_menit, 60)
    if jam > 0:
        return f"{jam} jam {menit} menit"
    return f"{menit} menit"


@app.before_request
def _enforce_ip_block():
    """Tolak semua request dari IP yang sedang diblokir (berlaku di kedua server)."""
    from flask import request, Response
    # Biarkan aset statis lolos agar halaman blokir tetap tampil rapi.
    if request.endpoint == 'static':
        return None
    ip = get_client_ip()
    blocked, sisa = is_ip_blocked(ip)
    if blocked:
        sisa_txt = _format_sisa(sisa) if sisa else 'beberapa saat'
        html = f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Akses Diblokir</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  body{{font-family:'Poppins',sans-serif;background:#1c3458;color:#fff;
       min-height:100vh;display:flex;align-items:center;justify-content:center;margin:0;padding:1.5rem;}}
  .box{{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);
        border-radius:18px;padding:2.5rem 2rem;max-width:440px;text-align:center;
        box-shadow:0 12px 40px rgba(0,0,0,.35);}}
  .ic{{font-size:3rem;margin-bottom:1rem;}}
  h1{{font-size:1.4rem;margin:0 0 .6rem;}}
  p{{color:rgba(255,255,255,.8);font-size:.95rem;line-height:1.6;margin:.4rem 0;}}
  .sisa{{margin-top:1.25rem;background:rgba(239,68,68,.18);border:1px solid rgba(252,165,165,.5);
         border-radius:12px;padding:.8rem 1rem;font-weight:700;color:#fca5a5;}}
</style></head>
<body><div class="box">
  <div class="ic">&#128274;</div>
  <h1>Akses Diblokir Sementara</h1>
  <p>Perangkat ini diblokir karena terlalu banyak percobaan login yang gagal.</p>
  <p>Demi keamanan sistem PEMIRA, akses dari IP Anda dinonaktifkan sementara.</p>
  <div class="sisa">Coba lagi dalam {sisa_txt}</div>
</div></body></html>"""
        return Response(html, status=403)
    return None
