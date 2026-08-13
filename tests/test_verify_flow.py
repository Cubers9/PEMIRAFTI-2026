"""
Test alur verifikasi lewat HTTP (black box) memakai Flask test client.

Batas jaringan/QR ditambal (monkeypatch) agar test deterministik & offline:
    * qr_engine.decode_qr        -> mengembalikan URL palsu
    * krs_verifier.download_krs  -> mengembalikan path palsu (tanpa unduh)
    * krs_verifier.extract_fields-> mengembalikan field KRS "asli"

Yang diuji adalah orkestrasi endpoint /verify di app_user.py, bukan
implementasi internal masing-masing engine (sudah diuji di unit test).
"""

import io

import pytest

# Impor modul rute agar endpoint terdaftar pada `app`.
import evoting.routes.user as app_user  # noqa: F401


VALID_URL = "https://baak.gunadarma.ac.id/validasi/546634"
KRS_ASLI = {"name": "BUDI SANTOSO", "npm": "50411234", "kelas": "3KA11 (L-p)"}


def _post_verify(client, *, name="Budi Santoso", npm="50411234",
                 kelas="3KA11", filename="krs.png", data=b"fakeimg"):
    """Kirim POST multipart ke /verify dengan berkas unggahan dummy."""
    return client.post(
        "/verify",
        data={
            "name": name,
            "npm": npm,
            "kelas": kelas,
            "krs_image": (io.BytesIO(data), filename),
        },
        content_type="multipart/form-data",
    )


@pytest.fixture()
def happy_path(monkeypatch, shared_module):
    """Tambal QR + unduh + ekstraksi sehingga alur bisa sampai cross-check."""
    monkeypatch.setattr(shared_module.qr_engine, "decode_qr",
                        lambda path: (VALID_URL, None))
    monkeypatch.setattr(shared_module.krs_verifier, "download_krs",
                        lambda url: ("/tmp/fake_krs_asli.pdf", None))
    monkeypatch.setattr(shared_module.krs_verifier, "extract_fields",
                        lambda path: (dict(KRS_ASLI), None))
    return shared_module


# --------------------------------------------------------------------------- #
# GET
# --------------------------------------------------------------------------- #
def test_get_verify_menampilkan_form(client):
    resp = client.get("/verify")
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Validasi input
# --------------------------------------------------------------------------- #
def test_field_wajib_kosong_ditolak(client):
    resp = _post_verify(client, name="", npm="", kelas="")
    assert resp.status_code == 200
    assert "wajib diisi".encode() in resp.data

def test_tanpa_berkas_ditolak(client):
    resp = client.post("/verify", data={
        "name": "Budi", "npm": "50411234", "kelas": "3KA11",
    }, content_type="multipart/form-data")
    assert "Unggah file KRS".encode() in resp.data

def test_format_berkas_tidak_didukung(client):
    resp = _post_verify(client, filename="krs.txt")
    assert "tidak didukung".encode() in resp.data


# --------------------------------------------------------------------------- #
# QR / domain / unduh gagal
# --------------------------------------------------------------------------- #
def test_qr_tidak_terbaca(client, monkeypatch, shared_module):
    monkeypatch.setattr(shared_module.qr_engine, "decode_qr",
                        lambda path: (None, "ERR_QR_NOT_FOUND"))
    resp = _post_verify(client)
    assert "QR code pada KRS tidak terbaca".encode() in resp.data

def test_domain_qr_bukan_sumber_resmi(client, monkeypatch, shared_module):
    monkeypatch.setattr(shared_module.qr_engine, "decode_qr",
                        lambda path: ("https://evil.com/krs", None))
    resp = _post_verify(client)
    assert "sumber resmi".encode() in resp.data

def test_unduh_gagal_tanpa_fallback(client, monkeypatch, shared_module):
    monkeypatch.setattr(shared_module.qr_engine, "decode_qr",
                        lambda path: (VALID_URL, None))
    monkeypatch.setattr(shared_module.krs_verifier, "download_krs",
                        lambda url: (None, "ERR_DOWNLOAD"))
    # Pastikan fallback lokal tidak aktif.
    monkeypatch.setattr(app_user, "_local_fallback", lambda url, uploaded_path=None: None)
    resp = _post_verify(client)
    assert "tidak dapat mengunduh KRS asli".encode() in resp.data


# --------------------------------------------------------------------------- #
# Cross-check
# --------------------------------------------------------------------------- #
def test_cross_check_gagal_npm_beda(client, happy_path):
    resp = _post_verify(client, npm="99999999")
    assert "Verifikasi gagal".encode() in resp.data

def test_verifikasi_sukses(client, happy_path):
    resp = _post_verify(client)
    assert resp.status_code == 200
    assert b"50411234" in resp.data
    # Sesi terverifikasi tersimpan.
    with client.session_transaction() as sess:
        assert sess.get("voter_npm") == "50411234"

def test_verifikasi_sukses_menulis_log_valid(client, happy_path):
    _post_verify(client)
    with happy_path.app.app_context():
        from evoting.core import KRSLog
        log = KRSLog.query.filter_by(npm="50411234").order_by(KRSLog.id.desc()).first()
        assert log is not None
        assert log.status == "VALID"


# --------------------------------------------------------------------------- #
# Cegah vote ganda
# --------------------------------------------------------------------------- #
def test_npm_sudah_vote_ditolak(client, happy_path):
    # Catat suara untuk NPM ini lebih dulu di blockchain in-memory.
    happy_path.blockchain.add_vote("50411234", "Paslon 01")
    resp = _post_verify(client)
    assert "sudah memberikan suara".encode() in resp.data
