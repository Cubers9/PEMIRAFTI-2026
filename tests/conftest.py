"""
Fixtures pytest untuk suite verifikasi PEMIRA.

Prinsip isolasi:
    * DB SQLite diarahkan ke berkas sementara per-sesi test — DB produksi
      (instance/evoting.db) tidak pernah tersentuh.
    * UPLOAD_FOLDER / DOWNLOAD_FOLDER juga diarahkan ke direktori sementara.
    * Tidak ada panggilan jaringan sungguhan: test HTTP menambal (monkeypatch)
      qr_engine.decode_qr dan krs_verifier.download_krs/extract_fields.
"""

import os
import tempfile
import shutil

import pytest


@pytest.fixture(scope="session")
def _tmp_root():
    """Direktori sementara akar untuk DB & folder unggahan selama sesi test."""
    root = tempfile.mkdtemp(prefix="pemira_test_")
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session")
def shared_module(_tmp_root):
    """
    Impor `shared` sekali, lalu ikat ulang DB ke SQLite sementara dan
    arahkan folder unggahan/unduhan ke direktori sementara.
    """
    uploads = os.path.join(_tmp_root, "uploads")
    downloads = os.path.join(_tmp_root, "downloads")
    os.makedirs(uploads, exist_ok=True)
    os.makedirs(downloads, exist_ok=True)

    import evoting.core as shared

    shared.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        UPLOAD_FOLDER=uploads,
        DOWNLOAD_FOLDER=downloads,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{os.path.join(_tmp_root, 'test.db')}",
    )
    shared.krs_verifier.download_folder = downloads

    # Ikat ulang engine SQLAlchemy ke URI sementara.
    with shared.app.app_context():
        shared.db.session.remove()
        for engine in shared.db.engines.values():
            engine.dispose()
    shared.app.extensions.pop("sqlalchemy", None)
    shared.db.init_app(shared.app)

    with shared.app.app_context():
        shared.db.create_all()

    return shared


@pytest.fixture()
def app(shared_module):
    """Flask app dengan DB bersih di setiap test."""
    shared = shared_module
    with shared.app.app_context():
        # Bersihkan seluruh tabel agar test saling terisolasi.
        for table in reversed(shared.db.metadata.sorted_tables):
            shared.db.session.execute(table.delete())
        shared.db.session.commit()
        # Reset blockchain in-memory ke hanya genesis block.
        from evoting.blockchain import Blockchain
        shared.blockchain.chain = Blockchain().chain
    yield shared.app


@pytest.fixture()
def client(app):
    """Flask test client (black-box HTTP)."""
    return app.test_client()


@pytest.fixture()
def verifier():
    """Instance KRSVerifier terisolasi dengan whitelist domain deterministik."""
    from evoting.engines.krs_verifier import KRSVerifier
    tmp = tempfile.mkdtemp(prefix="krs_verifier_")
    v = KRSVerifier(
        ocr_engine=None,
        download_folder=tmp,
        allowed_domains=["gunadarma.ac.id"],
        timeout=5,
        max_mb=10,
    )
    yield v
    shutil.rmtree(tmp, ignore_errors=True)
