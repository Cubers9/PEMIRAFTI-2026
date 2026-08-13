"""
KRS Verifier — inti mekanisme verifikasi baru.

Alur:
    URL (dari QR)  ->  validasi domain (whitelist, anti-SSRF)
                   ->  unduh KRS asli (PDF) dari sumber resmi
                   ->  ekstrak Nama / NPM / Kelas dari KRS asli
                   ->  cocokkan dengan input pemilih

Prinsip: acuan kebenaran adalah KRS ASLI hasil unduhan, bukan berkas yang
diunggah pemilih. Berkas unggahan hanya pembawa QR.
"""

import os
import re
import time
import ipaddress
from urllib.parse import urlparse

import requests
import fitz  # PyMuPDF

# Error codes
ERR_DOMAIN = "ERR_DOMAIN"       # domain tidak masuk whitelist / skema salah
ERR_DOWNLOAD = "ERR_DOWNLOAD"   # gagal mengunduh (timeout, jaringan, status != 200)
ERR_NOT_PDF = "ERR_NOT_PDF"     # berkas yang diunduh bukan PDF
ERR_EXTRACT = "ERR_EXTRACT"     # gagal mengekstrak field dari KRS asli


def _clean(value):
    """Normalisasi umum: upper, buang spasi berlebih."""
    return re.sub(r"\s+", " ", (value or "").strip()).upper()


def _norm_kelas(value):
    """Normalisasi kelas: buang sufiks '(L-p)' dan karakter non-alfanumerik."""
    v = _clean(value)
    v = re.sub(r"\(.*?\)", "", v)          # buang '(L-p)' dsb.
    v = re.sub(r"[^A-Z0-9]", "", v)        # sisakan alfanumerik saja
    return v


class KRSVerifier:
    def __init__(self, ocr_engine=None, download_folder="downloads",
                 allowed_domains=None, timeout=None, max_mb=None):
        self.ocr_engine = ocr_engine
        self.download_folder = download_folder
        os.makedirs(self.download_folder, exist_ok=True)

        env_domains = os.environ.get("KRS_ALLOWED_DOMAINS", "gunadarma.ac.id")
        self.allowed_domains = allowed_domains or [
            d.strip().lower() for d in env_domains.split(",") if d.strip()
        ]
        self.timeout = timeout or int(os.environ.get("KRS_DOWNLOAD_TIMEOUT", "10"))
        self.max_bytes = (max_mb or int(os.environ.get("KRS_MAX_DOWNLOAD_MB", "10"))) * 1024 * 1024

    # ------------------------------------------------------------------ #
    # 1. Validasi domain (anti-SSRF)
    # ------------------------------------------------------------------ #
    def is_allowed_domain(self, url):
        """
        True hanya jika URL memakai HTTPS dan host-nya cocok dengan salah satu
        domain di whitelist (host == domain atau subdomain darinya). IP literal
        selalu ditolak.
        """
        try:
            parsed = urlparse(url)
        except Exception:
            return False

        if parsed.scheme.lower() != "https":
            return False

        host = (parsed.hostname or "").lower()
        if not host:
            return False

        # Tolak IP literal (mencegah akses langsung ke jaringan internal).
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass

        for domain in self.allowed_domains:
            if host == domain or host.endswith("." + domain):
                return True
        return False

    # ------------------------------------------------------------------ #
    # 2. Unduh KRS asli
    # ------------------------------------------------------------------ #
    def download_krs(self, url):
        """
        Mengembalikan (path, None) bila berhasil, atau (None, ERR_*).
        Menerapkan timeout, batas ukuran, dan validasi tipe PDF.
        """
        if not self.is_allowed_domain(url):
            return None, ERR_DOMAIN

        try:
            resp = requests.get(url, timeout=self.timeout, stream=True,
                                 allow_redirects=True)
        except requests.RequestException as e:
            print(f"[krs_verifier] gagal unduh: {e}")
            return None, ERR_DOWNLOAD

        with resp:
            if resp.status_code != 200:
                return None, ERR_DOWNLOAD

            # Redirect tidak boleh keluar dari whitelist.
            if not self.is_allowed_domain(resp.url):
                return None, ERR_DOMAIN

            content_type = (resp.headers.get("content-type") or "").lower()

            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > self.max_bytes:
                    return None, ERR_NOT_PDF  # terlalu besar / bukan PDF wajar
                chunks.append(chunk)

            data = b"".join(chunks)

        # Validasi PDF: content-type ATAU magic bytes.
        is_pdf = "pdf" in content_type or data[:5] == b"%PDF-"
        if not is_pdf:
            return None, ERR_NOT_PDF

        filename = f"krs_asli_{int(time.time() * 1000)}.pdf"
        path = os.path.join(self.download_folder, filename)
        with open(path, "wb") as f:
            f.write(data)
        return path, None

    # ------------------------------------------------------------------ #
    # 3. Ekstraksi field dari KRS asli
    # ------------------------------------------------------------------ #
    def extract_fields(self, pdf_path):
        """
        Mengembalikan (fields, None) atau (None, ERR_EXTRACT).
        fields = {'name': str, 'npm': str, 'kelas': str}
        """
        text = ""
        try:
            doc = fitz.open(pdf_path)
            try:
                for page in doc:
                    text += page.get_text()
            finally:
                doc.close()
        except Exception as e:
            print(f"[krs_verifier] gagal baca PDF: {e}")

        fields = self._parse_fields(text)

        # Fallback OCR untuk KRS hasil pindai (teks kosong / tidak lengkap).
        if (not fields.get("npm") or not fields.get("name")) and self.ocr_engine:
            try:
                ocr_text = self.ocr_engine.extract_text(pdf_path)
                if ocr_text:
                    ocr_fields = self._parse_fields(ocr_text)
                    for k, v in ocr_fields.items():
                        if not fields.get(k) and v:
                            fields[k] = v
            except Exception as e:
                print(f"[krs_verifier] OCR fallback gagal: {e}")

        if not fields.get("npm"):
            return None, ERR_EXTRACT
        return fields, None

    def _parse_fields(self, text):
        # Nama: berhenti sebelum label berikutnya (NPM/KELAS/dst.) atau jeda
        # ganda, agar tidak menelan field lain saat semua berada di satu baris.
        name = self._search(
            r"NAMA\s*:?\s*(.+?)(?=\s{2,}|\s+NPM\b|\s+KELAS\b|\s+TEMPAT\b|"
            r"\s+PROGRAM\b|\s+FAKULTAS\b|\s+JURUSAN\b|$)",
            text,
        )
        npm = self._search(r"NPM\s*:?\s*(\d{7,10})", text)
        kelas = self._search(r"KELAS\s*:?\s*([0-9A-Za-z\-]+)", text)
        return {
            "name": name.strip() if name else "",
            "npm": npm.strip() if npm else "",
            "kelas": kelas.strip() if kelas else "",
        }

    @staticmethod
    def _search(pattern, text):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1) if m else ""

    # ------------------------------------------------------------------ #
    # 4. Cross-check input pemilih vs KRS asli
    # ------------------------------------------------------------------ #
    def cross_check(self, input_data, extracted):
        """
        Cocokkan Nama, NPM, Kelas. Mengembalikan (True, None, []) bila cocok,
        atau (False, ringkasan_alasan, daftar_field_salah) bila tidak.

        daftar_field_salah berisi dict per field yang tidak cocok:
        {'field': 'NPM', 'input': <input pemilih>, 'krs': <nilai di KRS asli>}
        sehingga pemilih tahu persis bagian mana yang keliru.
        """
        mismatches = []

        # NPM — pencocokan eksak.
        if _clean(input_data.get("npm")) != _clean(extracted.get("npm")):
            mismatches.append({'field': 'NPM',
                               'input': input_data.get("npm") or "",
                               'krs': extracted.get("npm") or ""})

        # Nama — pencocokan eksak setelah normalisasi.
        if _clean(input_data.get("name")) != _clean(extracted.get("name")):
            mismatches.append({'field': 'Nama',
                               'input': input_data.get("name") or "",
                               'krs': extracted.get("name") or ""})

        # Kelas — normalisasi (buang sufiks '(L-p)').
        if _norm_kelas(input_data.get("kelas")) != _norm_kelas(extracted.get("kelas")):
            mismatches.append({'field': 'Kelas',
                               'input': input_data.get("kelas") or "",
                               'krs': extracted.get("kelas") or ""})

        if mismatches:
            fields = ", ".join(m['field'] for m in mismatches)
            return False, f"{fields} tidak sesuai dengan KRS asli.", mismatches

        return True, None, []


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python krs_verifier.py <url>")
        sys.exit(1)

    v = KRSVerifier()
    url = sys.argv[1]
    print("allowed:", v.is_allowed_domain(url))
    path, err = v.download_krs(url)
    print("download:", path, err)
    if path:
        fields, err = v.extract_fields(path)
        print("fields:", fields, err)
