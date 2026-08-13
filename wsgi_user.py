"""Entry point server pemilih (port 8000).

Template & static kini berada di dalam package (evoting/templates, evoting/static),
sehingga Flask(__name__) sudah menemukannya otomatis — tanpa override path.
Jalankan:  gunicorn wsgi_user:app -b 0.0.0.0:8000
      atau: python wsgi_user.py
"""
from evoting.core import app, init_db

import evoting.routes.user  # noqa: E402,F401  (mendaftarkan route ke app)

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
