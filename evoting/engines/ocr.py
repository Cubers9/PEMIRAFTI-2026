"""
OCR Engine — ekstraksi TEKS dari KRS asli hasil unduhan.

Pada sistem baru, OCR bukan lagi gerbang identitas. Berkas yang diunggah
pemilih hanya pembawa QR (lihat qr_engine.py). OCR di sini berfungsi sebagai
CADANGAN krs_verifier.py: bila KRS asli yang diunduh adalah hasil pindai
(tanpa lapisan teks), OCR merender halaman PDF ke gambar lalu membacanya
sehingga field Nama/NPM/Kelas tetap bisa diekstrak.
"""

import re

import cv2
import pytesseract
import fitz  # PyMuPDF
from PIL import Image


class OCREngine:
    def __init__(self, tesseract_cmd=None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    # ------------------------------------------------------------------ #
    # Ekstraksi teks mentah (dipakai krs_verifier sebagai fallback)
    # ------------------------------------------------------------------ #
    def extract_text(self, file_path):
        """Kembalikan seluruh teks dari berkas KRS (gambar atau PDF)."""
        try:
            if file_path.lower().endswith(".pdf"):
                return self._pdf_text(file_path)
            return pytesseract.image_to_string(Image.open(file_path))
        except Exception as e:
            print(f"[ocr_engine] error: {e}")
            return ""

    def _pdf_text(self, pdf_path):
        """Teks langsung dari PDF; jika kosong, render halaman lalu OCR."""
        doc = fitz.open(pdf_path)
        try:
            full_text = "".join(page.get_text() for page in doc)
            if full_text.strip():
                return full_text

            # Fallback: render ke gambar dan OCR (KRS hasil pindai).
            ocr_text = ""
            for page in doc:
                pix = page.get_pixmap(dpi=300)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_text += pytesseract.image_to_string(img)
            return ocr_text
        finally:
            doc.close()

    # ------------------------------------------------------------------ #
    # Ekstraksi field terstruktur (opsional, dipakai bila diperlukan)
    # ------------------------------------------------------------------ #
    def extract_fields(self, file_path):
        """Kembalikan dict {'name','npm','kelas'} dari sebuah KRS."""
        text = self.extract_text(file_path)
        return {
            # Nama berhenti sebelum label berikutnya agar tidak menelan field
            # lain ketika NAMA/NPM/KELAS berada pada satu baris.
            "name": self._search(
                r"NAMA\s*:?\s*(.+?)(?=\s{2,}|\s+NPM\b|\s+KELAS\b|\s+TEMPAT\b|"
                r"\s+PROGRAM\b|\s+FAKULTAS\b|\s+JURUSAN\b|$)",
                text,
            ),
            "npm": self._search(r"NPM\s*:?\s*(\d{7,10})", text),
            "kelas": self._search(r"KELAS\s*:?\s*([0-9A-Za-z\-]+)", text),
        }

    @staticmethod
    def _search(pattern, text):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ""


if __name__ == "__main__":
    import sys

    engine = OCREngine()
    if len(sys.argv) >= 2:
        print(engine.extract_fields(sys.argv[1]))
    else:
        print("OCR Engine Initialized")
