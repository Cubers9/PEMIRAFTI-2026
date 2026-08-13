"""Seed data suara UJI COBA dengan timestamp TERSEBAR agar animasi timeline
terlihat berubah-ubah.

Paslon 01 = 300, Paslon 02 = 200 (total 500), disebar sepanjang sebuah fase
pemungutan selama SPREAD_HOURS jam. Urutan masuknya suara diacak (deterministik)
sehingga persentase naik-turun sebelum akhirnya stabil ke 60% : 40%.

Jalankan dari root project:

    python -m scripts.seed_dummy_votes
"""

import os
import sys
import random

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

from evoting.core import app, db, VoteBlock, reload_blockchain, sync_blockchain_to_db
from evoting.blockchain import Block

PASLON_01 = 300
PASLON_02 = 200
SPREAD_HOURS = 8          # fase pemungutan dianggap berlangsung 8 jam
BASE_TS = 1_786_000_000   # titik awal waktu (epoch) untuk data uji
SEED = 42                 # agar hasil acak konsisten tiap dijalankan


def seed():
    rng = random.Random(SEED)

    # Daftar semua suara lalu acak urutannya (biar dua paslon berselang-seling).
    votes = ["Paslon 01"] * PASLON_01 + ["Paslon 02"] * PASLON_02
    rng.shuffle(votes)

    span = SPREAD_HOURS * 3600
    # Timestamp acak dalam rentang fase, lalu diurutkan menaik.
    timestamps = sorted(BASE_TS + rng.uniform(0, span) for _ in votes)

    with app.app_context():
        # Kosongkan ledger lama supaya total pas 500.
        VoteBlock.query.delete()
        db.session.commit()

        # Bangun ulang chain dari genesis dengan timestamp yang kita kontrol.
        bc = reload_blockchain()
        for i, (vote, ts) in enumerate(zip(votes, timestamps), start=1):
            hashed = bc._hash_npm(f"DUMMY_{i:04d}")
            prev = bc.get_latest_block().hash
            block = Block(index=len(bc.chain), npm=hashed, vote=vote,
                          prev_hash=prev, timestamp=ts)
            bc.chain.append(block)

        sync_blockchain_to_db()

        results = bc.get_results()
        total = sum(results.values())
        print("Data uji (timestamp tersebar) berhasil dimasukkan:")
        for cand, count in results.items():
            print(f"  - {cand}: {count}")
        print(f"  TOTAL: {total}")
        print(f"  Rentang waktu: {SPREAD_HOURS} jam, {len(votes)} suara")
        print("\nBuka /results di server admin lalu klik 'Hitung Hasil Suara'.")


if __name__ == "__main__":
    seed()
