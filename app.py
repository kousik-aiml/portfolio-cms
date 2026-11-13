"""Personal portfolio website with a full admin dashboard.

Run:  python app.py        (then open http://127.0.0.1:5000/admin and create your password)
"""
import os
import secrets

from flask import Flask, abort, jsonify, request, send_from_directory, session
from markupsafe import Markup

import db
from schema import option_pairs
from forms import INLINE_EXTS, fmt_date, fmt_date_full, render_value
from seed import seed_if_empty


def create_app(data_dir=None):
    app = Flask(__name__)
    data_dir = os.path.abspath(data_dir or os.environ.get("PORTFOLIO_DATA_DIR") or
                               os.path.join(os.path.dirname(__file__), "data"))
    upload_dir = os.path.join(data_dir, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    key_file = os.path.join(data_dir, "secret_key")
    if not os.path.exists(key_file):
        with open(key_file, "w") as fh:
            fh.write(secrets.token_hex(32))
        os.chmod(key_file, 0o600)
    with open(key_file) as fh:
        secret = fh.read().strip()

    app.config.update(
        SECRET_KEY=secret,
        DATA_DIR=data_dir,
        DB_PATH=os.path.join(data_dir, "portfolio.db"),
        UPLOAD_DIR=upload_dir,
        MAX_CONTENT_LENGTH=int(os.environ.get("PORTFOLIO_MAX_UPLOAD_MB", "100")) * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME="portfolio_session",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
    )

    db.init_db(app.config["DB_PATH"])
    with app.app_context():
        seed_if_empty()
        db.get_db().commit()
    app.teardown_appcontext(db.close_db)
    app.jinja_env.globals["option_pairs"] = option_pairs

    # ------------------------------------------------------------------ CSRF + headers
    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    @app.before_request
    def check_csrf():
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
            if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
                abort(400, "Your form expired or is invalid. Go back, refresh the page and try again.")

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.path.startswith("/admin"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def errors(e):
        from flask import render_template
        code = getattr(e, "code", 500)
        msg = {413: "That upload is too large.", 404: "That page does not exist."}.get(
            code, getattr(e, "description", "Something went wrong."))
        return render_template("error.html", code=code, message=msg), code

    @app.context_processor
    def inject():
        return {
            "csrf_token": csrf_token,
            "is_admin": bool(session.get("admin")),
            "fmt_date": fmt_date,
            "fmt_date_full": fmt_date_full,
            "render_value": render_value,
            "option_pairs": option_pairs,
            "settings": db.all_settings(),
        }

    # ------------------------------------------------------------------ media
    @app.route("/media/<path:name>")
    def media(name):
        if "/" in name or ".." in name:
            abort(404)
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        inline = ext in INLINE_EXTS and request.args.get("dl") != "1"
        return send_from_directory(upload_dir, name, as_attachment=not inline,
                                   max_age=3600 if inline else None)

    @app.route("/healthz")
    def healthz():
        return jsonify(ok=True)

    from admin import bp as admin_bp
    from public import bp as public_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(public_bp)
    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host=os.environ.get("HOST", "127.0.0.1"),
                    port=int(os.environ.get("PORT", "5000")), debug=False)
