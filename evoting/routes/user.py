import os
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from werkzeug.utils import secure_filename
from evoting.core import (app, db, blockchain, qr_engine, krs_verifier, KRSLog,
                    sync_blockchain_to_db, init_db, reload_blockchain,
                    backup_blockchain_to_json,
                    KRS_LOCAL_FALLBACK_DIR,
                    get_voting_status, get_voting_window)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'heic'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.errorhandler(413)
def file_too_large(e):
    return render_template('verify.html', error="File terlalu besar. Maksimal 10 MB."), 413

def _fmt_dt(dt):
    return dt.strftime('%d %B %Y, %H:%M WIB') if dt else None


def _local_fallback(url, uploaded_path=None):
    """
    Fallback pengujian (env-gated): hanya aktif bila KRS_LOCAL_FALLBACK_DIR
    diset. Bila unduh live gagal, cari PDF lokal yang namanya memuat ID dari
    akhir URL (mis. .../validasi/546634 → berkas mengandung '546634'); jika
    tidak ketemu, gunakan berkas KRS yang diunggah sebagai sumber ekstraksi.
    Mengembalikan path lokal atau None. TIDAK aktif di produksi kecuali diset.
    """
    if not KRS_LOCAL_FALLBACK_DIR:
        return None
    if os.path.isdir(KRS_LOCAL_FALLBACK_DIR):
        ident = url.rstrip('/').split('/')[-1]
        if ident:
            for fname in os.listdir(KRS_LOCAL_FALLBACK_DIR):
                if ident in fname and fname.lower().endswith('.pdf'):
                    return os.path.join(KRS_LOCAL_FALLBACK_DIR, fname)
    return uploaded_path


@app.route('/', endpoint='user_index')
def index():
    status = get_voting_status()
    start, end = get_voting_window()
    return render_template('index.html',
                           voting_status=status,
                           voting_start_iso=start.strftime('%Y-%m-%dT%H:%M:%S') if start else None,
                           voting_end_iso=end.strftime('%Y-%m-%dT%H:%M:%S') if end else None,
                           voting_start_fmt=_fmt_dt(start),
                           voting_end_fmt=_fmt_dt(end))

@app.route('/verify', methods=['GET', 'POST'], endpoint='user_verify')
def verify():
    vs = get_voting_status()
    if vs != 'open':
        start, end = get_voting_window()
        return render_template('verify.html',
                               voting_blocked=True,
                               voting_status=vs,
                               voting_start_fmt=_fmt_dt(start),
                               voting_end_fmt=_fmt_dt(end))

    if request.method == 'POST':
        # --- 1. Ambil & validasi input pemilih --------------------------
        name = (request.form.get('name') or '').strip()
        npm = (request.form.get('npm') or '').strip()
        kelas = (request.form.get('kelas') or '').strip()

        def _keep():
            return {'form_name': name, 'form_npm': npm, 'form_kelas': kelas}

        def _log_krs(status, keterangan, filename=None, qr_url=None):
            """Catat satu baris audit upload KRS untuk dashboard admin."""
            db.session.add(KRSLog(
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                npm=npm, name=name, kelas=kelas,
                filename=filename, qr_url=qr_url,
                status=status, keterangan=keterangan,
            ))
            db.session.commit()

        if not name or not npm or not kelas:
            return render_template('verify.html',
                                   error="Nama, NPM, dan Kelas wajib diisi.", **_keep())

        if 'krs_image' not in request.files or request.files['krs_image'].filename == '':
            return render_template('verify.html',
                                   error="Unggah file KRS terlebih dahulu.", **_keep())

        file = request.files['krs_image']
        if not allowed_file(file.filename):
            return render_template('verify.html',
                                   error="Format file tidak didukung. Gunakan JPG, PNG, PDF, atau HEIC.",
                                   **_keep())

        # Cegah vote ganda: NPM yang sudah tercatat di blockchain ditolak.
        if blockchain.has_voted(npm):
            _log_krs('GAGAL', 'NPM sudah memberikan suara.')
            return render_template('verify.html',
                                   error=f"NPM {npm} sudah memberikan suara.", **_keep())

        # Simpan berkas unggahan (pembawa QR).
        filename = secure_filename(file.filename)
        unique_filename = f"{int(time.time())}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)

        # --- 2. Baca QR dari berkas unggahan ----------------------------
        url, qr_err = qr_engine.decode_qr(filepath)
        if qr_err:
            _log_krs('GAGAL', 'QR code pada KRS tidak terbaca.', filename=unique_filename)
            return render_template('verify.html',
                                   error="QR code pada KRS tidak terbaca. Pastikan KRS memuat QR dan gambar jelas.",
                                   **_keep())

        # --- 3. Validasi domain (anti-SSRF) -----------------------------
        if not krs_verifier.is_allowed_domain(url):
            _log_krs('GAGAL', 'Tautan QR bukan dari sumber resmi (gunadarma.ac.id).',
                     filename=unique_filename, qr_url=url)
            return render_template('verify.html',
                                   error="Tautan pada QR tidak berasal dari sumber resmi (gunadarma.ac.id).",
                                   **_keep())

        # --- 4. Unduh KRS asli ------------------------------------------
        original_path, dl_err = krs_verifier.download_krs(url)
        if dl_err:
            original_path = _local_fallback(url, uploaded_path=filepath)
            if not original_path:
                _log_krs('GAGAL', 'Gagal mengunduh KRS asli dari sumber resmi.',
                         filename=unique_filename, qr_url=url)
                return render_template('verify.html',
                                       error="Sistem tidak dapat mengunduh KRS asli dari sumber resmi saat ini. Silakan coba lagi nanti.",
                                       **_keep())

        # --- 5. Ekstrak field dari KRS asli -----------------------------
        extracted, ex_err = krs_verifier.extract_fields(original_path)
        if ex_err:
            _log_krs('GAGAL', 'Gagal mengekstrak data dari KRS asli.',
                     filename=unique_filename, qr_url=url)
            return render_template('verify.html',
                                   error="Gagal mengekstrak data dari KRS asli. Pastikan KRS jelas dan lengkap.",
                                   **_keep())

        # --- 6. Cross-check input pemilih vs KRS asli -------------------
        ok, reason, mismatches = krs_verifier.cross_check(
            {'name': name, 'npm': npm, 'kelas': kelas}, extracted)
        if not ok:
            _log_krs('GAGAL', f'Cross-check gagal: {reason}',
                     filename=unique_filename, qr_url=url)
            return render_template('verify.html',
                                   error=f"Verifikasi gagal: {reason}",
                                   mismatches=mismatches, **_keep())

        # --- 7. Valid ---------------------------------------------------
        _log_krs('VALID', 'Terverifikasi — data cocok dengan KRS asli.',
                 filename=unique_filename, qr_url=url)
        session['voter_npm'] = npm
        session['voter_name'] = name
        return render_template('verify.html', verified_student={
            'npm': npm,
            'name': name,
            'kelas': extracted.get('kelas'),
        })

    # GET: bila sudah punya sesi terverifikasi, arahkan sesuai status vote.
    if 'voter_npm' in session:
        if blockchain.has_voted(session['voter_npm']):
            return redirect(url_for('user_results'))
        return redirect(url_for('user_ballot'))

    return render_template('verify.html')

@app.route('/ballot', endpoint='user_ballot')
def ballot():
    if get_voting_status() != 'open':
        return redirect(url_for('user_index'))
    if 'voter_npm' not in session:
        return redirect(url_for('user_verify'))
    return render_template('ballot.html', name=session['voter_name'], npm=session['voter_npm'])

@app.route('/cast_vote', methods=['POST'], endpoint='user_cast_vote')
def cast_vote():
    if get_voting_status() != 'open':
        return jsonify({"success": False, "message": "Voting sudah ditutup."}), 403
    if 'voter_npm' not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    candidate = request.form.get('candidate')
    npm = session['voter_npm']

    # Muat ulang chain terbaru, lalu cegah vote ganda via blockchain.
    bc = reload_blockchain()
    if bc.has_voted(npm):
        session.clear()
        return redirect(url_for('user_results'))

    new_block = bc.add_vote(npm, candidate)
    hashed_id = new_block.npm   # ID pemilih (NPM ter-hash) yang tercatat di ledger

    sync_blockchain_to_db()
    backup_blockchain_to_json()

    session.clear()
    # Simpan sesaat untuk ditampilkan sekali di halaman konfirmasi.
    session['last_vote_id'] = hashed_id
    return redirect(url_for('user_vote_success'))


@app.route('/vote-success', endpoint='user_vote_success')
def vote_success():
    # Hanya bisa diakses tepat setelah memilih; ID diambil sekali lalu dihapus.
    hashed_id = session.pop('last_vote_id', None)
    if not hashed_id:
        return redirect(url_for('user_index'))
    return render_template('vote_success.html', hashed_id=hashed_id)

@app.route('/cek-suara', methods=['GET', 'POST'], endpoint='user_check_vote')
def check_vote():
    """Cek pilihan berdasarkan ID pemilih (hashed) yang disimpan user."""
    result = None
    voter_id = ''
    error = None

    if request.method == 'POST':
        voter_id = (request.form.get('voter_id') or '').strip()
        if not voter_id:
            error = "Masukkan ID pemilih Anda terlebih dahulu."
        else:
            bc = reload_blockchain()
            # Cari blok yang ID pemilihnya cocok (lewati genesis di index 0).
            match = next((b for b in bc.chain[1:] if b.npm == voter_id), None)
            if match:
                result = {'vote': match.vote, 'index': match.index}
            else:
                error = ("ID pemilih tidak ditemukan pada blockchain. "
                         "Periksa kembali penulisannya.")

    return render_template('check_vote.html',
                           result=result, voter_id=voter_id, error=error)


@app.route('/api/results-data', endpoint='user_results_data')
def results_data():
    bc = reload_blockchain()
    return jsonify(bc.get_results())

@app.route('/results', endpoint='user_results')
def results():
    bc = reload_blockchain()
    res = bc.get_results()
    invalid_blocks = bc.get_invalid_blocks()
    is_valid = len(invalid_blocks) == 0
    total_votes = sum(res.values())

    return render_template('results.html',
                           results=res,
                           total_votes=total_votes,
                           is_valid=is_valid,
                           invalid_blocks=invalid_blocks,
                           chain=bc.chain)
