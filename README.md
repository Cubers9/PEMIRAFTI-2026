# VoteChain — Sistem E-Voting BEM FTI UG

Sistem e-voting berbasis blockchain untuk Pemilihan Umum Raya (PEMIRA) BEM Fakultas Teknologi Industri, Universitas Gunadarma. Validasi identitas menggunakan OCR pada foto KRS mahasiswa.

---

## Struktur Folder

```
.
├── app_user.py        # Server voter (port 8000)
├── app_admin.py       # Server admin/KPU (port 8001)
├── shared.py          # Database, blockchain, konfigurasi bersama
├── blockchain.py      # Implementasi blockchain SHA-256
├── ocr_engine.py      # Ekstraksi NPM dari foto KRS
├── requirements.txt
├── .env               # Secrets (jangan di-commit)
├── .env.example       # Template .env
├── instance/          # Database SQLite (auto-generate)
├── uploads/           # File KRS mahasiswa (jangan di-commit)
├── backups/           # Backup JSON blockchain
├── static/
│   ├── css/style.css  # CSS voter UI
│   └── css/admin.css  # CSS admin panel
└── templates/
    ├── base.html
    ├── index.html
    ├── verify.html
    ├── ballot.html
    ├── results.html
    ├── admin_students.html
    ├── admin_verify.html
    └── admin_voter_audit.html
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Pastikan `tesseract-ocr` sudah terinstall di sistem:
- macOS: `brew install tesseract tesseract-lang`
- Ubuntu: `apt install tesseract-ocr tesseract-ocr-ind`

### 2. Konfigurasi environment

```bash
cp .env.example .env
# Edit .env dan isi nilai SECRET_KEY, SECRET_SALT, dan ADMIN_PASSWORD
```

Generate nilai acak:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Jalankan server

Jalankan dua server secara bersamaan di terminal berbeda:

```bash
# Terminal 1 — Server voter (mahasiswa)
python app_user.py
# Akses di: http://localhost:8000

# Terminal 2 — Server admin (KPU)
python app_admin.py
# Akses di: http://localhost:8001
```

Atau gunakan Docker:

```bash
docker-compose up --build
```

---

## Cara Penggunaan

### Admin KPU (port 8001)

Login menggunakan HTTP Basic Auth dengan `ADMIN_PASSWORD` dari file `.env`.

| Halaman | URL | Fungsi |
|---|---|---|
| Database Mahasiswa | `/admin/students` | Tambah, import CSV/Excel, hapus mahasiswa |
| Verifikasi KRS | `/admin/verify-krs` | Review manual KRS status PENDING |
| Audit Pemilih | `/admin/voter-audit` | Blacklist suara yang tidak sah |
| Hasil Live | `/results` | Lihat perhitungan suara dan blockchain explorer |

### Voter/Mahasiswa (port 8000)

1. Buka `http://localhost:8000`
2. Klik **Mulai Memilih**
3. Upload foto KRS (JPG/PNG/PDF, maks 10 MB)
4. Sistem OCR memvalidasi NPM otomatis
5. Pilih paslon dan konfirmasi

---

## Reset Voting

Untuk menghapus semua data voting (misalnya untuk demo ulang):

```bash
python clear_votes.py
```

Atau hapus file database secara manual:

```bash
rm instance/evoting.db
rm backups/blockchain_backup.json
```

Kemudian restart server — database akan dibuat ulang otomatis.

---

## Catatan Skripsi

- Blockchain dalam sistem ini bersifat **terpusat** (satu server), bukan distributed. Cocok sebagai proof-of-concept dengan asumsi server terpercaya.
- Anonimitas pemilih dijaga dengan hashing NPM menggunakan SHA-256 + salt rahasia.
- Kapasitas yang diuji: 600–1000 pemilih.
# E-Voting-Pemira-Blockchain-Intergrated
