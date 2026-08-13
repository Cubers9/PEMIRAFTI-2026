"""
QR Engine — membaca QR code dari KRS yang diunggah pemilih.

Berkas KRS yang diunggah pemilih hanya berfungsi sebagai PEMBAWA QR code.
Isi QR adalah tautan (URL) ke KRS asli di server Gunadarma. Modul ini hanya
bertugas mengekstrak URL tersebut; validasi domain & pengunduhan ditangani
oleh krs_verifier.py.

Decoder utama: OpenCV (cv2.QRCodeDetector) — tidak memerlukan dependency
sistem tambahan (berbeda dengan pyzbar yang butuh libzbar). Jika pyzbar atau
WeChat QR detector kebetulan tersedia, keduanya dipakai sebagai cadangan untuk
foto yang buram.
"""

import re

import cv2
import numpy as np
import fitz  # PyMuPDF

ERR_QR_NOT_FOUND = "ERR_QR_NOT_FOUND"

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class QREngine:
    def __init__(self):
        self._detector = cv2.QRCodeDetector()
        # WeChat detector lebih tahan terhadap gambar buram; opsional.
        self._wechat = None
        try:
            self._wechat = cv2.wechat_qrcode.WeChatQRCode()
        except Exception:
            self._wechat = None

    # ------------------------------------------------------------------ #
    # API utama
    # ------------------------------------------------------------------ #
    def decode_qr(self, file_path):
        """
        Mengembalikan (url, None) bila QR berisi URL berhasil dibaca,
        atau (None, ERR_QR_NOT_FOUND) bila gagal.
        """
        try:
            candidates = self._collect_payloads(file_path)
        except Exception as e:
            print(f"[qr_engine] error membaca berkas: {e}")
            return None, ERR_QR_NOT_FOUND

        for payload in candidates:
            if payload and _URL_RE.match(payload.strip()):
                return payload.strip(), None

        return None, ERR_QR_NOT_FOUND

    def read_all(self, file_path):
        """Kembalikan semua payload QR yang terbaca (untuk CLI/diagnostik)."""
        try:
            return self._collect_payloads(file_path)
        except Exception as e:
            print(f"[qr_engine] error membaca berkas: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _collect_payloads(self, file_path):
        """Kumpulkan semua string QR dari berkas (gambar atau PDF)."""
        if file_path.lower().endswith(".pdf"):
            images = self._pdf_to_images(file_path)
        else:
            img = cv2.imread(file_path)
            images = [img] if img is not None else []

        payloads = []
        for img in images:
            if img is None:
                continue
            for variant in self._image_variants(img):
                payloads.extend(self._decode_image(variant))
                if payloads:
                    # Sudah ketemu — tidak perlu variant lain untuk gambar ini.
                    break
        # Dedup sambil menjaga urutan.
        seen = set()
        unique = []
        for p in payloads:
            if p and p not in seen:
                seen.add(p)
                unique.append(p)
        return unique

    def _pdf_to_images(self, pdf_path):
        """Render tiap halaman PDF ke gambar pada beberapa DPI."""
        images = []
        doc = fitz.open(pdf_path)
        try:
            for page in doc:
                for dpi in (200, 300, 400):
                    pix = page.get_pixmap(dpi=dpi)
                    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                        pix.height, pix.width, pix.n
                    )
                    if pix.n == 4:  # RGBA -> RGB
                        arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)
                    elif pix.n == 1:  # gray -> RGB
                        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
                    images.append(arr.copy())
        finally:
            doc.close()
        return images

    def _image_variants(self, img):
        """Hasilkan beberapa varian gambar untuk memperbesar peluang decode."""
        variants = [img]
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
            # Upscale 2x untuk QR kecil / foto beresolusi rendah.
            up = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            variants.append(up)
            # Otsu threshold untuk foto buram / kontras rendah.
            _, thresh = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )
            variants.append(thresh)
        except Exception:
            pass
        return variants

    def _decode_image(self, img):
        """Coba semua decoder yang tersedia pada satu gambar."""
        results = []

        # 1) OpenCV multi-QR.
        try:
            ok, decoded, _, _ = self._detector.detectAndDecodeMulti(img)
            if ok:
                results.extend([d for d in decoded if d])
        except Exception:
            pass

        # 2) OpenCV single-QR (kadang berhasil saat multi gagal).
        if not results:
            try:
                data, _, _ = self._detector.detectAndDecode(img)
                if data:
                    results.append(data)
            except Exception:
                pass

        # 3) WeChat detector (opsional).
        if not results and self._wechat is not None:
            try:
                decoded, _ = self._wechat.detectAndDecode(img)
                results.extend([d for d in decoded if d])
            except Exception:
                pass

        # 4) pyzbar (opsional, jika terinstal).
        if not results:
            try:
                from pyzbar.pyzbar import decode as zbar_decode

                for obj in zbar_decode(img):
                    try:
                        results.append(obj.data.decode("utf-8", "ignore"))
                    except Exception:
                        pass
            except Exception:
                pass

        return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python qr_engine.py path/ke/krs.pdf")
        sys.exit(1)

    engine = QREngine()
    path = sys.argv[1]
    payloads = engine.read_all(path)
    if not payloads:
        print("Tidak ada QR code yang terbaca pada berkas ini.")
        sys.exit(2)

    for p in payloads:
        jenis = "URL/link" if _URL_RE.match(p.strip()) else "teks/data"
        print(f"[{jenis}] {p}")
