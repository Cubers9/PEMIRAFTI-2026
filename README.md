# VoteChain - Sistem E-Voting Berbasis Blockchain

Aplikasi pemungutan suara elektronik (e-voting) untuk Pemilihan Umum Raya
(PEMIRA) organisasi kemahasiswaan. Setiap suara dicatat pada **blockchain
SHA-256** sehingga tidak dapat diubah, sementara identitas pemilih diverifikasi
otomatis lewat **scan QR + OCR pada KRS** dan dijaga anonim dengan hashing NPM
bergaram (salted hash).

Sistem berjalan sebagai **dua aplikasi terpisah**: server pemilih dan server
admin/KPU, masing-masing pada port sendiri agar panel admin terisolasi dari
publik.

---

## Fitur Utama

- **Blockchain ledger** — setiap suara menjadi satu blok berantai (SHA-256);
  perubahan satu blok merusak seluruh rantai sehingga manipulasi terdeteksi.
- **Verifikasi KRS otomatis** — QR pada KRS dipindai, KRS asli diunduh dari
  domain resmi (proteksi anti-SSRF), lalu Nama/NPM/Kelas dicocokkan via OCR.
- **Anonimitas pemilih** — NPM di-hash dengan SHA-256 + salt rahasia sebelum
  masuk ledger; identitas asli tidak tersimpan di rantai.
- **Cegah suara ganda** — satu NPM hanya bisa memilih sekali (dicek terhadap
  ledger).
- **Panel admin/KPU** — kelola daftar pemilih valid, review KRS, atur jendela
  waktu voting, dan lihat hasil live + blockchain explorer.
- **Proteksi brute-force** — login admin yang gagal berulang memblokir IP
  lintas kedua server (state di DB bersama).

---

## Arsitektur

```
.
├── evoting/                 # Package aplikasi
│   ├── config.py            # Konstanta & path (dibaca dari .env)
│   ├── core.py              # Flask app, DB (SQLAlchemy), model, blockchain
│   ├── blockchain.py        # Implementasi blockchain SHA-256
│   ├── engines/
│   │   ├── ocr.py           # OCR (pytesseract) — ekstraksi teks KRS
│   │   ├── qr.py            # Pemindai QR (OpenCV)
│   │   └── krs_verifier.py  # Unduh KRS asli + cross-check field
│   ├── routes/
│   │   ├── user.py          # Endpoint server pemilih
│   │   └── admin.py         # Endpoint server admin/KPU
│   ├── templates/           # Jinja2 (voter + admin)
│   └── static/              # CSS, JS, gambar
├── wsgi_user.py             # Entrypoint server pemilih  (port 8000)
├── wsgi_admin.py            # Entrypoint server admin/KPU (port 8001)
├── scripts/
│   ├── clear_votes.py       # Reset seluruh data voting
│   └── seed_dummy_votes.py  # Isi suara dummy untuk demo
├── tests/                   # Pytest (unit + flow HTTP)
├── uploads/                 # KRS terunggah (runtime, tidak di-commit)
├── downloads/               # KRS asli hasil unduhan (runtime sementara)
├── backups/                 # Backup JSON blockchain (runtime)
├── requirements.txt
├── .env.example             # Template konfigurasi
├── Dockerfile
└── docker-compose.yml
```

Database SQLite dibuat otomatis di `instance/evoting.db` saat pertama dijalankan.

---

## Persyaratan Sistem

- Python 3.10+
- `tesseract-ocr` (mesin OCR native)
  - macOS: `brew install tesseract tesseract-lang`
  - Ubuntu/Debian: `sudo apt install tesseract-ocr tesseract-ocr-ind`
- Untuk OpenCV di server headless (Linux): paket `libgl1` dan `libglib2.0-0`
  (sudah termasuk dalam `Dockerfile`).

---

## Setup

### 1. Install dependency Python

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Konfigurasi environment

```bash
cp .env.example .env
```

Isi `SECRET_KEY`, `SECRET_SALT`, dan `ADMIN_PASSWORD`. Untuk membuat nilai acak:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Menjalankan

### Development (Flask, auto-reload)

Dua server di dua terminal:

```bash
# Terminal 1 — server pemilih  → http://localhost:8000
python wsgi_user.py

# Terminal 2 — server admin/KPU → http://localhost:8001
python wsgi_admin.py
```

### Produksi (gunicorn)

```bash
gunicorn wsgi_user:app  -b 0.0.0.0:8000
gunicorn wsgi_admin:app -b 0.0.0.0:8001
```

### Docker

```bash
docker-compose up --build
# pemilih → http://localhost:8000   admin → http://localhost:8001
```

---

## Cara Penggunaan

### Pemilih / Mahasiswa (port 8000)

1. Buka `http://localhost:8000` lalu mulai memilih.
2. Unggah foto/PDF KRS (JPG/PNG/PDF, maks 10 MB).
3. Sistem memindai QR KRS, mengunduh KRS asli dari domain resmi, dan
   mencocokkan Nama/NPM/Kelas.
4. Setelah tervalidasi, pilih paslon dan konfirmasi. Suara masuk ke blockchain.
5. Pemilih dapat mengecek suaranya sendiri lewat halaman **Cek Suara**.

### Admin / KPU (port 8001)

Login dengan HTTP Basic Auth memakai `ADMIN_PASSWORD` dari `.env`.

| Fungsi | URL |
|---|---|
| Dashboard | `/` |
| Hasil live + blockchain explorer | `/results` |
| Review KRS (verifikasi) | `/admin/verify-krs` |
| Ekspor data KRS | `/admin/verify-krs/export` |
| Daftar pemilih valid | `/admin/pemilih-valid` |
| Pengaturan (jendela waktu voting) | `/admin/settings` |

---

## Konfigurasi Verifikasi KRS

Diatur lewat `.env` (lihat `.env.example`):

| Variabel | Fungsi |
|---|---|
| `KRS_ALLOWED_DOMAINS` | Domain resmi sumber KRS (anti-SSRF), pisahkan koma |
| `KRS_DOWNLOAD_TIMEOUT` | Batas waktu unduh KRS asli (detik) |
| `KRS_MAX_DOWNLOAD_MB` | Batas ukuran berkas unduhan (MB) |
| `KRS_LOCAL_FALLBACK_DIR` | Opsional: folder KRS lokal untuk demo offline (kosongkan di produksi) |

---

## Reset Data Voting

```bash
python scripts/clear_votes.py
```

Atau hapus manual lalu restart (DB dibuat ulang otomatis):

```bash
rm -f instance/evoting.db backups/blockchain_backup.json
```

---

## Testing

```bash
pytest
```

Mencakup unit test logika verifikasi KRS dan test alur HTTP end-to-end
(offline, tanpa jaringan) untuk endpoint `/verify`.

---

## Catatan Teknis

- Blockchain bersifat **terpusat** (single-server) — cocok sebagai
  proof-of-concept dengan asumsi server tepercaya, bukan jaringan
  terdistribusi.
- Kedua server berbagi satu database SQLite sehingga status pemilih, ledger,
  dan blokir IP konsisten lintas proses.
- Kapasitas yang telah diuji: ~600–1000 pemilih.
