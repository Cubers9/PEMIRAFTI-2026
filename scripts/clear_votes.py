"""Reset seluruh data voting (ledger DB + berkas unggahan/unduhan).

Jalankan dari root project:  python -m scripts.clear_votes
"""

import os
import sys

# Pastikan root project ada di sys.path agar package `evoting` bisa diimpor
# walau skrip dijalankan langsung (python scripts/clear_votes.py).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

from evoting.core import app, db, VoteBlock

def clear_data():
    with app.app_context():
        print("Cleaning up voting data...")

        # 1. Clear Blockchain Blocks from DB
        VoteBlock.query.delete()
        db.session.commit()
        print("- Database records reset.")

        # 4. Remove blockchain.json
        if os.path.exists('blockchain.json'):
            os.remove('blockchain.json')
            print("- blockchain.json removed.")

        # 5. Clean up uploads folder
        upload_folder = app.config['UPLOAD_FOLDER']
        for filename in os.listdir(upload_folder):
            file_path = os.path.join(upload_folder, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")
        print("- Uploaded KRS files cleared.")

        # 6. Clean up downloads folder (KRS asli hasil unduhan)
        download_folder = app.config.get('DOWNLOAD_FOLDER', 'downloads')
        if os.path.isdir(download_folder):
            for filename in os.listdir(download_folder):
                file_path = os.path.join(download_folder, filename)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    print(f"Error deleting {file_path}: {e}")
            print("- Downloaded KRS asli files cleared.")

        print("\nSUCCESS: All voting data has been cleared. Restart the apps to apply changes.")

if __name__ == "__main__":
    clear_data()
