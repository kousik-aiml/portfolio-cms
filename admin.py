"""Admin dashboard routes."""
import io
import json
import re
import time
from functools import wraps

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import datatools
import db
import present
from forms import delete_upload, file_names, parse_form
from public import render_detail, render_site
from schema import (CUSTOM_TYPES, CUSTOM_TYPE_KEYS, PROFILE_GROUPS, RESERVED_SLUGS, SECTIONS, all_targets,
                    get_section, item_title, profile_fields, slugify)

bp = Blueprint("admin", __name__)
_failed = {}  # ip -> (count, first_time)


# --------------------------------------------------------------------------- auth
def password_set():
    return bool(db.get_setting("admin_password"))


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not password_set():
            return redirect(url_for("admin.setup"))
        if not session.get("admin"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def _safe_next(target):
    return target if target and target.startswith("/admin") and not target.startswith("//") else url_for("admin.dashboard")


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if password_set():
        return redirect(url_for("admin.login"))
    if request.method == "POST":
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        if len(pw) < 8:
            flash("Use at least 8 characters.", "error")
        elif pw != pw2:
            flash("The two passwords do not match.", "error")
        else:
            db.set_setting("admin_password", generate_password_hash(pw))
            db.get_db().commit()
            session.clear()
            session["admin"] = True
            session.permanent = True
            flash("Password created. Welcome to your dashboard!", "ok")
            return redirect(url_for("admin.dashboard"))
    return render_template("admin/setup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not password_set():
        return redirect(url_for("admin.setup"))
    if request.method == "POST":
        ip = request.remote_addr or "?"
        count, first = _failed.get(ip, (0, time.time()))
        if time.time() - first > 900:
            count, first = 0, time.time()
        if count >= 8:
            flash("Too many attempts. Try again in a few minutes.", "error")
        elif check_password_hash(db.get_setting("admin_password"), request.form.get("password", "")):
            _failed.pop(ip, None)
            session.clear()
            session["admin"] = True
            session.permanent = True
            return redirect(_safe_next(request.args.get("next")))
        else:
            _failed[ip] = (count + 1, first)
            time.sleep(0.5)
            flash("Wrong password.", "error")
    return render_template("admin/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("public.index"))


# --------------------------------------------------------------------------- helpers
def nav_sections():
    out = []
    for s in db.site_sections():
        if s["kind"] == "profile":
            continue
        out.append(s)
    return out


@bp.context_processor
def admin_ctx():
    return {"nav_sections": nav_sections() if session.get("admin") else []}


def referenced_files():
    names = set()
    conn = db.get_db()
    for r in conn.execute("SELECT data, published_data FROM items"):
        for col in ("data", "published_data"):
            for v in (db.jload(r[col], {}) or {}).values():
                names.update(file_names(v))
    for r in conn.execute("SELECT value, published_value FROM profile_fields"):
        for col in ("value", "published_value"):
            names.update(file_names(db.jload(r[col])))
    return names


def collect_files(*datas):
    names = set()
    for d in datas:
        for v in (d or {}).values():
            names.update(file_names(v))
    return names


def drop_unreferenced(candidates):
    live = referenced_files()
    for n in set(candidates) - live:
        delete_upload(n)


def get_item_or_404(item_id):
    it = db.get_item(item_id)
    if not it:
        abort(404)
    sec = get_section(it["section"])
    if not sec:
        abort(404)
    return it, sec


def back_to_section(key):
    return redirect(url_for("admin.section_list", key=key))


# --------------------------------------------------------------------------- dashboard
@bp.route("/")
@login_required
def dashboard():
    conn = db.get_db()
    stats = []
    total_drafts = total_dirty = 0
    for s in nav_sections():
        items = db.list_items(s["key"])
        drafts = sum(1 for i in items if i["status"] == "draft")
        dirty = sum(1 for i in items if i["dirty"])
        total_drafts += drafts
        total_dirty += dirty
        stats.append({"key": s["key"], "title": s["title"], "count": len(items), "drafts": drafts,
                      "dirty": dirty, "hidden": sum(1 for i in items if not i["visible"]),
                      "visible": bool(s["visible"])})
    prof = conn.execute(
        "SELECT COUNT(*) c FROM profile_fields WHERE value IS NOT published_value OR visible!=published_visible"
    ).fetchone()["c"]
    return render_template("admin/dashboard.html", stats=stats, total_drafts=total_drafts,
                           total_dirty=total_dirty, profile_unpublished=prof)


# --------------------------------------------------------------------------- profile
@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    defs = profile_fields()
    current = present.get_profile_all()
    conn = db.get_db()
    if request.method == "POST":
        existing = {k: v[0] for k, v in current.items()}
        before = collect_files({k: v for k, v in existing.items()})
        data, errors = parse_form(defs, request.form, request.files, existing)
        if errors:
            for e in errors:
                flash(e, "error")
            vis = {f["key"]: request.form.get("vis_" + f["key"]) == "1" for f in defs}
            merged = {k: (data.get(k, existing.get(k)), vis.get(k, True)) for k in vis}
            return render_template("admin/profile.html", defs=defs, values=merged, groups=PROFILE_GROUPS)
        publish = request.form.get("action") == "publish"
        for f in defs:
            k = f["key"]
            vis = 1 if request.form.get("vis_" + k) == "1" else 0
            text = db.jdump(data[k])
            conn.execute(
                "INSERT INTO profile_fields(key,value,visible,published_value,published_visible) VALUES(?,?,?,NULL,0) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, visible=excluded.visible", (k, text, vis))
        if publish:
            conn.execute("UPDATE profile_fields SET published_value=value, published_visible=visible")
        conn.commit()
        drop_unreferenced(before)
        conn.commit()
        flash("Profile published — visitors now see it." if publish else
              "Profile saved as a draft. Visitors still see the previous published version.", "ok")
        return redirect(url_for("admin.profile"))
    return render_template("admin/profile.html", defs=defs, values=current, groups=PROFILE_GROUPS)


# --------------------------------------------------------------------------- section lists
@bp.route("/s/<key>")
@login_required
def section_list(key):
    sec = get_section(key)
    if not sec:
        abort(404)
    items = db.list_items(key)
    rows = [{"item": i, "title": item_title(sec, i["data"]),
             "sub": " · ".join(str(i["data"].get(k)) for k in sec.get("subtitle", []) if i["data"].get(k))}
            for i in items]
    return render_template("admin/section_list.html", sec=sec, rows=rows,
                           default_resume=db.get_setting("default_resume"),
                           on_site=bool((db.site_section(key) or {}).get("visible", 1)))


@bp.route("/s/<key>/new", methods=["GET", "POST"])
@bp.route("/i/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def item_edit(key=None, item_id=None):
    item = None
    if item_id:
        item, sec = get_item_or_404(item_id)
        key = sec["key"]
    else:
        sec = get_section(key)
        if not sec:
            abort(404)
    if request.method == "POST":
        old = item["data"] if item else {}
        data, errors = parse_form(sec["fields"], request.form, request.files, old)
        action = request.form.get("action", "draft")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("admin/item_form.html", sec=sec, item=item, data=data)
        publish = action == "publish"
        if item:
            db.save_item_data(item["id"], data, publish=publish)
            iid = item["id"]
        else:
            iid = db.create_item(key, data, publish=publish)
        db.get_db().execute("UPDATE items SET visible=? WHERE id=?",
                            (1 if request.form.get("visible") == "1" else 0, iid))
        db.get_db().commit()
        if item:
            drop_unreferenced(collect_files(old, item["published_data"]))
            db.get_db().commit()
        flash(("Published." if publish else "Saved as draft.") + f" “{item_title(sec, data)}”", "ok")
        if action == "preview":
            return redirect(url_for("admin.item_preview", item_id=iid))
        if request.form.get("stay") == "1":
            return redirect(url_for("admin.item_edit", item_id=iid))
        return back_to_section(key)
    return render_template("admin/item_form.html", sec=sec, item=item, data=item["data"] if item else {})


@bp.route("/i/<int:item_id>/preview")
@login_required
def item_preview(item_id):
    it, sec = get_item_or_404(item_id)
    return render_detail(sec["key"], it["uid"], preview=True)


@bp.route("/i/<int:item_id>/do/<action>", methods=["POST"])
@login_required
def item_action(item_id, action):
    it, sec = get_item_or_404(item_id)
    conn = db.get_db()
    if action == "publish":
        db.publish_item(item_id)
        flash("Published.", "ok")
    elif action == "unpublish":
        db.unpublish_item(item_id)
        flash("Moved back to draft — no longer shown to visitors.", "ok")
    elif action == "hide":
        conn.execute("UPDATE items SET visible=0 WHERE id=?", (item_id,))
        flash("Hidden from visitors.", "ok")
    elif action == "show":
        conn.execute("UPDATE items SET visible=1 WHERE id=?", (item_id,))
        flash("Visible to visitors (if published).", "ok")
    elif action == "default" and sec["key"] == "resumes":
        db.set_setting("default_resume", it["uid"])
        flash("Default resume updated.", "ok")
    elif action in ("up", "down"):
        ids = [i["id"] for i in db.list_items(sec["key"])]
        idx = ids.index(item_id)
        j = idx - 1 if action == "up" else idx + 1
        if 0 <= j < len(ids):
            ids[idx], ids[j] = ids[j], ids[idx]
            db.set_positions("items", ids)
    elif action == "duplicate":
        data = dict(it["data"])
        for k in ("name", "title", "job_title", "institution", "label"):
            if data.get(k):
                data[k] = f"{data[k]} (copy)"
                break
        db.create_item(sec["key"], data, publish=False)
        flash("Duplicated as a draft.", "ok")
    else:
        abort(400)
    conn.commit()
    return back_to_section(sec["key"])


@bp.route("/i/<int:item_id>/delete", methods=["GET", "POST"])
@login_required
def item_delete(item_id):
    it, sec = get_item_or_404(item_id)
    title = item_title(sec, it["data"])
    if request.method == "POST":
        if request.form.get("confirm") != "yes":
            abort(400)
        files = collect_files(it["data"], it["published_data"])
        db.get_db().execute("DELETE FROM items WHERE id=?", (item_id,))
        if db.get_setting("default_resume") == it["uid"]:
            db.set_setting("default_resume", "")
        db.get_db().commit()
        drop_unreferenced(files)
        db.get_db().commit()
        flash(f"“{title}” was permanently deleted.", "ok")
        return back_to_section(sec["key"])
    return render_template("admin/confirm.html", heading=f"Delete “{title}”?",
                           message="This permanently removes the record and its uploaded files. It cannot be undone.",
                           cancel=url_for("admin.section_list", key=sec["key"]), button="Delete permanently")


@bp.route("/s/<key>/reorder", methods=["POST"])
@login_required
def section_reorder(key):
    ids = request.get_json(silent=True) or {}
    ids = [int(i) for i in ids.get("ids", []) if str(i).isdigit()]
    valid = {i["id"] for i in db.list_items(key)}
    if set(ids) != valid:
        abort(400)
    db.set_positions("items", ids)
    db.get_db().commit()
    return jsonify(ok=True)


@bp.route("/s/<key>/publish-all", methods=["POST"])
@login_required
def publish_all(key):
    if not get_section(key):
        abort(404)
    now = db.utcnow()
    db.get_db().execute(
        "UPDATE items SET published_data=data, status='published', published_at=? WHERE section=?", (now, key))
    db.get_db().commit()
    flash("Everything in this section is now published.", "ok")
    return back_to_section(key)


# --------------------------------------------------------------------------- website sections
@bp.route("/sections", methods=["GET", "POST"])
@login_required
def sections():
    conn = db.get_db()
    if request.method == "POST":
        for s in db.site_sections():
            k = s["key"]
            if "title_" + k not in request.form:
                continue
            conn.execute(
                "UPDATE site_sections SET title=?, intro=?, visible=?, layout=? WHERE key=?",
                ((request.form.get("title_" + k) or s["title"]).strip()[:120],
                 (request.form.get("intro_" + k) or "").strip()[:2000],
                 1 if request.form.get("visible_" + k) == "1" else 0,
                 request.form.get("layout_" + k) if request.form.get("layout_" + k) in ("cards", "timeline", "list")
                 else s["layout"], k))
        conn.commit()
        flash("Website sections saved.", "ok")
        return redirect(url_for("admin.sections"))
    return render_template("admin/sections.html", rows=db.site_sections())


@bp.route("/sections/new", methods=["POST"])
@login_required
def section_new():
    title = (request.form.get("title") or "").strip()[:120]
    if not title:
        flash("Give the section a name.", "error")
        return redirect(url_for("admin.sections"))
    base = slugify(title, "section")
    key, n = base, 2
    while key in RESERVED_SLUGS or db.site_section(key):
        key = f"{base}_{n}"
        n += 1
    pos = db.get_db().execute("SELECT COALESCE(MAX(position),-1)+1 p FROM site_sections").fetchone()["p"]
    db.get_db().execute(
        "INSERT INTO site_sections(key,title,intro,kind,visible,position,layout) VALUES(?,?,?,?,?,?,?)",
        (key, title, (request.form.get("intro") or "").strip()[:2000], "custom", 1, pos,
         request.form.get("layout") if request.form.get("layout") in ("cards", "timeline", "list") else "cards"))
    db.get_db().commit()
    flash(f"Section “{title}” created. Add entries to it from the sidebar.", "ok")
    return redirect(url_for("admin.section_list", key=key))


@bp.route("/sections/<key>/move/<direction>", methods=["POST"])
@login_required
def section_move(key, direction):
    keys = [s["key"] for s in db.site_sections()]
    if key not in keys or direction not in ("up", "down"):
        abort(400)
    i = keys.index(key)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(keys):
        keys[i], keys[j] = keys[j], keys[i]
        db.set_positions("site_sections", keys, id_column="key")
        db.get_db().commit()
    return redirect(url_for("admin.sections"))


@bp.route("/sections/reorder", methods=["POST"])
@login_required
def sections_reorder():
    keys = (request.get_json(silent=True) or {}).get("keys", [])
    if set(keys) != {s["key"] for s in db.site_sections()}:
        abort(400)
    db.set_positions("site_sections", keys, id_column="key")
    db.get_db().commit()
    return jsonify(ok=True)


@bp.route("/sections/<key>/delete", methods=["GET", "POST"])
@login_required
def section_delete(key):
    s = db.site_section(key)
    if not s or s["kind"] != "custom":
        abort(404)
    if request.method == "POST":
        if request.form.get("confirm") != "yes":
            abort(400)
        files = set()
        for it in db.list_items(key):
            files |= collect_files(it["data"], it["published_data"])
        conn = db.get_db()
        conn.execute("DELETE FROM items WHERE section=?", (key,))
        conn.execute("DELETE FROM custom_fields WHERE target=?", (key,))
        conn.execute("DELETE FROM site_sections WHERE key=?", (key,))
        conn.commit()
        drop_unreferenced(files)
        conn.commit()
        flash(f"Section “{s['title']}” and all its entries were deleted.", "ok")
        return redirect(url_for("admin.sections"))
    n = len(db.list_items(key))
    return render_template("admin/confirm.html", heading=f"Delete the section “{s['title']}”?",
                           message=f"This permanently deletes the section, its {n} entr{'y' if n == 1 else 'ies'} and its custom fields.",
                           cancel=url_for("admin.sections"), button="Delete section permanently")


# --------------------------------------------------------------------------- custom fields
def _options_from(text):
    return [o.strip() for o in (text or "").splitlines() if o.strip()][:200]


@bp.route("/fields", methods=["GET", "POST"])
@login_required
def fields():
    conn = db.get_db()
    targets = all_targets()
    valid_targets = {k for k, _ in targets}
    if request.method == "POST":
        label = (request.form.get("label") or "").strip()[:120]
        typ = request.form.get("type")
        target = request.form.get("target")
        if not label or typ not in CUSTOM_TYPE_KEYS or target not in valid_targets:
            flash("Choose a name, a field type and where the field belongs.", "error")
            return redirect(url_for("admin.fields"))
        options = _options_from(request.form.get("options"))
        if typ in ("select", "multiselect") and not options:
            flash("Dropdown and multiple-selection fields need at least one option (one per line).", "error")
            return redirect(url_for("admin.fields"))
        base = slugify(label)
        key, n = base, 2
        while conn.execute("SELECT 1 FROM custom_fields WHERE target=? AND key=?", (target, key)).fetchone():
            key = f"{base}_{n}"
            n += 1
        pos = conn.execute("SELECT COALESCE(MAX(position),-1)+1 p FROM custom_fields WHERE target=?",
                           (target,)).fetchone()["p"]
        conn.execute(
            "INSERT INTO custom_fields(uid,key,label,type,options,target,help,show_public,position) VALUES(?,?,?,?,?,?,?,?,?)",
            (db.new_uid(), key, label, typ, db.jdump(options), target,
             (request.form.get("help") or "").strip()[:300], 1 if request.form.get("show_public") == "1" else 0, pos))
        conn.commit()
        flash(f"Field “{label}” added. It now appears in the editor for “{dict(targets)[target]}”.", "ok")
        return redirect(url_for("admin.fields", target=target))
    rows = [dict(r, options=db.jload(r["options"], []))
            for r in conn.execute("SELECT * FROM custom_fields ORDER BY target, position, id")]
    return render_template("admin/fields.html", rows=rows, targets=targets, types=CUSTOM_TYPES,
                           target_names=dict(targets), selected=request.args.get("target", "profile"))


@bp.route("/fields/<int:fid>/edit", methods=["POST"])
@login_required
def field_edit(fid):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM custom_fields WHERE id=?", (fid,)).fetchone()
    if not row:
        abort(404)
    label = (request.form.get("label") or "").strip()[:120] or row["label"]
    options = _options_from(request.form.get("options")) if row["type"] in ("select", "multiselect") else []
    if row["type"] in ("select", "multiselect") and not options:
        flash("This field needs at least one option.", "error")
        return redirect(url_for("admin.fields", target=row["target"]))
    conn.execute("UPDATE custom_fields SET label=?, options=?, help=?, show_public=? WHERE id=?",
                 (label, db.jdump(options), (request.form.get("help") or "").strip()[:300],
                  1 if request.form.get("show_public") == "1" else 0, fid))
    conn.commit()
    flash("Field updated.", "ok")
    return redirect(url_for("admin.fields", target=row["target"]))


@bp.route("/fields/<int:fid>/move/<direction>", methods=["POST"])
@login_required
def field_move(fid, direction):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM custom_fields WHERE id=?", (fid,)).fetchone()
    if not row or direction not in ("up", "down"):
        abort(404)
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM custom_fields WHERE target=? ORDER BY position, id", (row["target"],))]
    i = ids.index(fid)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
        db.set_positions("custom_fields", ids)
        conn.commit()
    return redirect(url_for("admin.fields", target=row["target"]))


@bp.route("/fields/<int:fid>/delete", methods=["GET", "POST"])
@login_required
def field_delete(fid):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM custom_fields WHERE id=?", (fid,)).fetchone()
    if not row:
        abort(404)
    if request.method == "POST":
        if request.form.get("confirm") != "yes":
            abort(400)
        ck = "cf_" + row["key"]
        files = set()
        if row["target"] == "profile":
            for col in ("value", "published_value"):
                pass
            r = conn.execute("SELECT value, published_value FROM profile_fields WHERE key=?", (ck,)).fetchone()
            if r:
                files |= set(file_names(db.jload(r["value"]))) | set(file_names(db.jload(r["published_value"])))
            conn.execute("DELETE FROM profile_fields WHERE key=?", (ck,))
        else:
            for it in conn.execute("SELECT * FROM items WHERE section=?", (row["target"],)).fetchall():
                d, p = db.jload(it["data"], {}), db.jload(it["published_data"])
                files |= set(file_names(d.get(ck))) | set(file_names((p or {}).get(ck)))
                d.pop(ck, None)
                if isinstance(p, dict):
                    p.pop(ck, None)
                conn.execute("UPDATE items SET data=?, published_data=? WHERE id=?",
                             (db.jdump(d), db.jdump(p) if p is not None else None, it["id"]))
        conn.execute("DELETE FROM custom_fields WHERE id=?", (fid,))
        conn.commit()
        drop_unreferenced(files)
        conn.commit()
        flash(f"Field “{row['label']}” and its values were deleted.", "ok")
        return redirect(url_for("admin.fields", target=row["target"]))
    return render_template("admin/confirm.html", heading=f"Delete the field “{row['label']}”?",
                           message="The field and every value you entered for it will be permanently removed.",
                           cancel=url_for("admin.fields", target=row["target"]), button="Delete field permanently")


# --------------------------------------------------------------------------- settings
@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    if request.method == "POST":
        form = request.form.get("form")
        if form == "password":
            cur, new, new2 = (request.form.get(k, "") for k in ("current", "new", "new2"))
            if not check_password_hash(db.get_setting("admin_password"), cur):
                flash("Current password is wrong.", "error")
            elif len(new) < 8:
                flash("New password must be at least 8 characters.", "error")
            elif new != new2:
                flash("The new passwords do not match.", "error")
            else:
                db.set_setting("admin_password", generate_password_hash(new))
                db.get_db().commit()
                flash("Password changed.", "ok")
        else:
            accent = request.form.get("accent", "")
            db.set_setting("site_title", (request.form.get("site_title") or "").strip()[:120])
            db.set_setting("tagline", (request.form.get("tagline") or "").strip()[:200])
            db.set_setting("footer", (request.form.get("footer") or "").strip()[:300])
            if re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
                db.set_setting("accent", accent)
            db.get_db().commit()
            flash("Site settings saved.", "ok")
        return redirect(url_for("admin.settings_page"))
    return render_template("admin/settings.html")


# --------------------------------------------------------------------------- preview
@bp.route("/preview/")
@login_required
def preview():
    return render_site(True)


@bp.route("/preview/s/<key>/<uid>")
@login_required
def preview_detail(key, uid):
    return render_detail(key, uid, True)


# --------------------------------------------------------------------------- data control
@bp.route("/data")
@login_required
def data_page():
    return render_template("admin/data.html")


def _json_download(payload, name):
    buf = io.BytesIO(json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"))
    return send_file(buf, mimetype="application/json", as_attachment=True,
                     download_name=f"{name}-{time.strftime('%Y%m%d-%H%M')}.json")


@bp.route("/data/export/personal.json")
@login_required
def export_personal():
    return _json_download(datatools.export_personal(), "personal-information")


@bp.route("/data/export/website.json")
@login_required
def export_website():
    return _json_download(datatools.export_site(), "website-content")


@bp.route("/data/backup.zip")
@login_required
def backup():
    return send_file(datatools.backup_zip(), mimetype="application/zip", as_attachment=True,
                     download_name=f"portfolio-backup-{time.strftime('%Y%m%d-%H%M')}.zip")


@bp.route("/data/import", methods=["POST"])
@login_required
def data_import():
    up = request.files.get("file")
    mode = request.form.get("mode", "merge")
    if not up or not up.filename:
        flash("Choose a JSON file to import.", "error")
        return redirect(url_for("admin.data_page"))
    if mode == "replace" and request.form.get("confirm") != "yes":
        flash("Tick the confirmation box to replace existing content.", "error")
        return redirect(url_for("admin.data_page"))
    try:
        payload = json.loads(up.read().decode("utf-8"))
        stats = datatools.import_personal(payload, mode)
    except (ValueError, UnicodeDecodeError) as e:
        db.get_db().rollback()
        flash(f"Import failed: {e}", "error")
        return redirect(url_for("admin.data_page"))
    flash("Import complete: {items} records, {profile_fields} profile fields, {custom_fields} custom fields, "
          "{sections} sections ({skipped} skipped).".format(**stats), "ok")
    return redirect(url_for("admin.data_page"))


@bp.route("/data/restore", methods=["POST"])
@login_required
def data_restore():
    up = request.files.get("file")
    if not up or not up.filename:
        flash("Choose a backup .zip to restore.", "error")
    elif request.form.get("confirm") != "yes":
        flash("Tick the confirmation box — restoring replaces everything.", "error")
    else:
        try:
            n = datatools.restore_backup(up.stream)
            flash(f"Backup restored ({n} files). A copy of the previous database was kept as portfolio.db.before-restore.", "ok")
        except ValueError as e:
            flash(f"Restore failed: {e}", "error")
    return redirect(url_for("admin.data_page"))
