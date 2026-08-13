"""Entry point server admin/KPU (port 8001).

Template & static kini berada di dalam package (evoting/templates, evoting/static),
sehingga Flask(__name__) sudah menemukannya otomatis — tanpa override path.
Jalankan:  gunicorn wsgi_admin:app -b 0.0.0.0:8001
      atau: python wsgi_admin.py
"""
from evoting.core import app, init_db

import evoting.routes.admin  # noqa: E402,F401  (mendaftarkan route ke app)

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=True)
