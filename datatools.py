"""Export / import / backup / restore."""
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile

import db
from flask import current_app
from schema import CUSTOM_TYPE_KEYS, SECTIONS

FORMAT = "portfolio-cms/1"
SETTING_KEYS = ("site_title", "tagline", "accent", "footer", "default_resume")
KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_ZIP_BYTES = 1024 * 1024 * 1024


def _rows(sql, args=()):
    return [dict(r) for r in db.get_db().execute(sql, args)]


# --------------------------------------------------------------------------- export
def export_personal():
    conn = db.get_db()
    profile = {r["key"]: {"value": db.jload(r["value"], ""), "visible": bool(r["visible"]),
                          "published_value": db.jload(r["published_value"], ""),
                          "published_visible": bool(r["published_visible"])}
               for r in conn.execute("SELECT * FROM profile_fields")}
    items = []
    for r in conn.execute("SELECT * FROM items ORDER BY section, position, id"):
        items.append({
            "uid": r["uid"], "section": r["section"], "data": db.jload(r["data"], {}),
            "published_data": db.jload(r["published_data"]) if r["published_data"] is not None else None,
            "status": r["status"], "visible": bool(r["visible"]), "position": r["position"],
        })
    return {
        "format": FORMAT, "kind": "personal", "exported_at": db.utcnow(),
        "settings": {k: db.get_setting(k) for k in SETTING_KEYS},
        "site_sections": _rows("SELECT key,title,intro,kind,visible,position,layout FROM site_sections ORDER BY position"),
        "custom_fields": [dict(r, options=db.jload(r["options"], [])) for r in
                          _rows("SELECT key,label,type,options,target,help,show_public,position FROM custom_fields ORDER BY id")],
        "profile": profile, "items": items,
        "note": "Uploaded files are referenced by filename. Use 'Download full backup' to include the files.",
    }


def export_site():
    """What visitors can currently see (published + visible only)."""
    conn = db.get_db()
    visible_keys = {s["key"] for s in db.site_sections(visible_only=True)}
    profile = {r["key"]: db.jload(r["published_value"], "")
               for r in conn.execute("SELECT * FROM profile_fields WHERE published_visible=1")}
    sections = []
    for s in db.site_sections(visible_only=True):
        if s["kind"] == "profile":
            continue
        items = [{"id": r["uid"], **db.jload(r["published_data"], {})}
                 for r in conn.execute(
                     "SELECT * FROM items WHERE section=? AND status='published' AND visible=1 "
                     "AND published_data IS NOT NULL ORDER BY position, id", (s["key"],))]
        sections.append({"key": s["key"], "title": s["title"], "intro": s["intro"], "items": items})
    return {"format": FORMAT, "kind": "website", "exported_at": db.utcnow(),
            "site_title": db.get_setting("site_title"), "visible_sections": sorted(visible_keys),
            "profile": profile, "sections": sections}


def backup_zip():
    """Zip with a consistent copy of the database plus every uploaded file."""
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "portfolio.db")
        src = sqlite3.connect(current_app.config["DB_PATH"])
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "portfolio.db")
            z.writestr("MANIFEST.json", json.dumps({"format": FORMAT, "kind": "backup", "created_at": db.utcnow()}))
            up = current_app.config["UPLOAD_DIR"]
            for name in sorted(os.listdir(up)):
                p = os.path.join(up, name)
                if os.path.isfile(p):
                    z.write(p, "uploads/" + name)
    buf.seek(0)
    return buf


# --------------------------------------------------------------------------- import
def _valid_section_keys():
    keys = set(SECTIONS)
    keys |= {r["key"] for r in _rows("SELECT key FROM site_sections")}
    return keys


def import_personal(payload, mode="merge"):
    """Import a JSON export. mode: 'merge' (add/update by id) or 'replace' (wipe content first)."""
    if not isinstance(payload, dict) or payload.get("format") != FORMAT or payload.get("kind") != "personal":
        raise ValueError("This is not a personal-information export from this application.")
    if mode not in ("merge", "replace"):
        raise ValueError("Unknown import mode.")
    conn = db.get_db()
    stats = {"items": 0, "profile_fields": 0, "custom_fields": 0, "sections": 0, "skipped": 0}
    if mode == "replace":
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM custom_fields")
        conn.execute("DELETE FROM site_sections WHERE kind='custom'")

    for s in payload.get("site_sections") or []:
        key = s.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            stats["skipped"] += 1
            continue
        kind = s.get("kind") if s.get("kind") in ("builtin", "custom", "profile") else "custom"
        if key in SECTIONS or key in ("about", "contact"):
            kind = "profile" if key in ("about", "contact") else "builtin"
        conn.execute(
            "INSERT INTO site_sections(key,title,intro,kind,visible,position,layout) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET title=excluded.title,intro=excluded.intro,visible=excluded.visible,"
            "position=excluded.position,layout=excluded.layout",
            (key, str(s.get("title") or key)[:120], str(s.get("intro") or "")[:2000], kind,
             1 if s.get("visible", 1) else 0, int(s.get("position") or 0),
             s.get("layout") if s.get("layout") in ("cards", "timeline", "list") else "cards"))
        stats["sections"] += 1

    for c in payload.get("custom_fields") or []:
        if not (isinstance(c.get("key"), str) and KEY_RE.match(c["key"]) and c.get("type") in CUSTOM_TYPE_KEYS
                and isinstance(c.get("target"), str)):
            stats["skipped"] += 1
            continue
        conn.execute(
            "INSERT INTO custom_fields(uid,key,label,type,options,target,help,show_public,position) "
            "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(target,key) DO UPDATE SET label=excluded.label,"
            "type=excluded.type,options=excluded.options,help=excluded.help,show_public=excluded.show_public,"
            "position=excluded.position",
            (db.new_uid(), c["key"], str(c.get("label") or c["key"])[:120], c["type"],
             db.jdump([str(o) for o in (c.get("options") or [])][:200]), c["target"][:40],
             str(c.get("help") or "")[:300], 1 if c.get("show_public", 1) else 0, int(c.get("position") or 0)))
        stats["custom_fields"] += 1

    for key, p in (payload.get("profile") or {}).items():
        if not isinstance(key, str) or not isinstance(p, dict) or len(key) > 60:
            stats["skipped"] += 1
            continue
        conn.execute(
            "INSERT INTO profile_fields(key,value,visible,published_value,published_visible) VALUES(?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,visible=excluded.visible,"
            "published_value=excluded.published_value,published_visible=excluded.published_visible",
            (key, db.jdump(p.get("value", "")), 1 if p.get("visible", 1) else 0,
             db.jdump(p.get("published_value", p.get("value", ""))),
             1 if p.get("published_visible", 0) else 0))
        stats["profile_fields"] += 1

    valid = _valid_section_keys()
    for it in payload.get("items") or []:
        if not isinstance(it, dict) or it.get("section") not in valid or not isinstance(it.get("data"), dict):
            stats["skipped"] += 1
            continue
        uid = it.get("uid") if isinstance(it.get("uid"), str) and re.fullmatch(r"[0-9a-f]{32}", it["uid"]) else db.new_uid()
        pub = it.get("published_data") if isinstance(it.get("published_data"), dict) else None
        status = "published" if (it.get("status") == "published" and pub is not None) else "draft"
        now = db.utcnow()
        existing = conn.execute("SELECT id, section FROM items WHERE uid=?", (uid,)).fetchone()
        if existing and existing["section"] != it["section"]:
            uid = db.new_uid()
            existing = None
        vals = (db.jdump(it["data"]), db.jdump(pub) if pub is not None else None, status,
                1 if it.get("visible", 1) else 0, int(it.get("position") or 0), now)
        if existing:
            conn.execute("UPDATE items SET data=?,published_data=?,status=?,visible=?,position=?,updated_at=? WHERE uid=?",
                         vals + (uid,))
        else:
            conn.execute(
                "INSERT INTO items(uid,section,data,published_data,status,visible,position,created_at,updated_at,published_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (uid, it["section"], vals[0], vals[1], status, vals[3], vals[4], now, now,
                 now if status == "published" else None))
        stats["items"] += 1

    for k, v in (payload.get("settings") or {}).items():
        if k in SETTING_KEYS and isinstance(v, str):
            db.set_setting(k, v[:500])
    conn.commit()
    return stats


# --------------------------------------------------------------------------- restore
def restore_backup(fileobj):
    try:
        z = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile:
        raise ValueError("That file is not a valid backup (.zip).")
    infos = z.infolist()
    if sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
        raise ValueError("Backup is too large to restore.")
    names = {i.filename for i in infos}
    if "portfolio.db" not in names:
        raise ValueError("This zip does not contain portfolio.db — it is not a backup made by this application.")

    with tempfile.TemporaryDirectory() as tmp:
        new_db = os.path.join(tmp, "portfolio.db")
        with z.open("portfolio.db") as src, open(new_db, "wb") as dst:
            shutil.copyfileobj(src, dst)
        try:
            chk = sqlite3.connect(new_db)
            tables = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            integrity = chk.execute("PRAGMA integrity_check").fetchone()[0]
            chk.close()
        except sqlite3.DatabaseError:
            raise ValueError("The database inside this backup is damaged.")
        if integrity != "ok" or not db.REQUIRED_TABLES <= tables:
            raise ValueError("The database inside this backup is not valid for this application.")

        up_dir = current_app.config["UPLOAD_DIR"]
        staged = os.path.join(tmp, "uploads")
        os.makedirs(staged)
        for i in infos:
            m = re.fullmatch(r"uploads/([0-9a-f]{32}\.[a-z0-9]{1,6})", i.filename)
            if m:
                with z.open(i) as src, open(os.path.join(staged, m.group(1)), "wb") as dst:
                    shutil.copyfileobj(src, dst)

        db.close_db()
        shutil.copy2(current_app.config["DB_PATH"], current_app.config["DB_PATH"] + ".before-restore")
        for name in os.listdir(up_dir):
            os.remove(os.path.join(up_dir, name))
        for name in os.listdir(staged):
            shutil.move(os.path.join(staged, name), os.path.join(up_dir, name))
        for suffix in ("-wal", "-shm"):
            try:
                os.remove(current_app.config["DB_PATH"] + suffix)
            except OSError:
                pass
        shutil.copyfile(new_db, current_app.config["DB_PATH"])
    return len(os.listdir(up_dir))
