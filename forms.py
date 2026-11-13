"""Turning submitted forms into stored data, and stored data into safe HTML."""
import os
import re
import uuid
from datetime import date, datetime

from flask import current_app
from markupsafe import Markup, escape
from werkzeug.utils import secure_filename

from sanitize import sanitize_html

IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
DOC_EXTS = IMAGE_EXTS | {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "csv", "txt",
                         "md", "zip", "ipynb", "json", "odt", "rtf"}
INLINE_EXTS = IMAGE_EXTS | {"pdf"}
SINGLE_FILE = {"image", "file"}
MULTI_FILE = {"images", "files"}
SAFE_URL = re.compile(r"^(https?://|mailto:|tel:)", re.I)


# --------------------------------------------------------------------------- helpers
def clean_url(value):
    v = (value or "").strip()
    if not v:
        return ""
    if SAFE_URL.match(v):
        return v
    if re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", v, re.I):  # bare domain
        return "https://" + v
    return ""


def allowed_exts(field):
    if field.get("exts"):
        return set(field["exts"].split(","))
    return IMAGE_EXTS if field["type"] in ("image", "images") else DOC_EXTS


def save_upload(storage, field, errors):
    name = secure_filename(storage.filename or "")
    if not name:
        return None
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in allowed_exts(field):
        errors.append(f"“{name}” was not uploaded: .{ext or '?'} files are not allowed for {field['label']}.")
        return None
    stored = f"{uuid.uuid4().hex}.{ext}"
    storage.save(os.path.join(current_app.config["UPLOAD_DIR"], stored))
    return {"f": stored, "n": name}


def delete_upload(stored):
    if stored and re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]+", stored):
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_DIR"], stored))
        except OSError:
            pass


def file_names(value):
    """All stored filenames referenced by a field value."""
    if isinstance(value, dict) and value.get("f"):
        return [value["f"]]
    if isinstance(value, list):
        return [v["f"] for v in value if isinstance(v, dict) and v.get("f")]
    return []


def _split_tags(text):
    return [t.strip() for t in re.split(r"[,\n]", text or "") if t.strip()]


# --------------------------------------------------------------------------- parsing
def parse_form(fields, form, files, existing=None):
    """Return (data, errors) from a submitted request form."""
    existing = existing or {}
    data, errors = {}, []
    for f in fields:
        key, typ = f["key"], f["type"]
        name = "f_" + key
        if typ in ("text", "textarea", "email", "phone", "date", "select", "combo", "ref"):
            val = (form.get(name) or "").strip()
            if typ == "select" and val and f.get("options") and val not in [o[0] for o in _pairs(f)]:
                val = ""
        elif typ in ("url", "videourl"):
            raw = form.get(name) or ""
            val = clean_url(raw)
            if raw.strip() and not val:
                errors.append(f"{f['label']}: “{raw.strip()}” is not a valid web address.")
        elif typ == "number":
            raw = (form.get(name) or "").strip()
            try:
                val = float(raw) if raw else ""
                if val != "" and val == int(val):
                    val = int(val)
            except ValueError:
                val = ""
                errors.append(f"{f['label']}: “{raw}” is not a number.")
        elif typ == "checkbox":
            val = form.get(name) in ("1", "on", "true")
        elif typ == "richtext":
            val = sanitize_html(form.get(name))
        elif typ == "tags":
            val = _split_tags(form.get(name))
        elif typ == "multiselect":
            allowed = {o[0] for o in _pairs(f)}
            val = [v for v in form.getlist(name) if v in allowed]
        elif typ == "list":
            val = [v.strip() for v in form.getlist(name + "[]") if v.strip()]
        elif typ == "urllist":
            val = []
            for raw in form.getlist(name + "[]"):
                u = clean_url(raw)
                if u:
                    val.append(u)
                elif raw.strip():
                    errors.append(f"{f['label']}: “{raw.strip()}” is not a valid web address.")
        elif typ == "links":
            val = []
            for label, raw in zip(form.getlist(name + "__label[]"), form.getlist(name + "__url[]")):
                u = clean_url(raw)
                if u:
                    val.append({"label": label.strip() or u, "url": u})
                elif raw.strip():
                    errors.append(f"{f['label']}: “{raw.strip()}” is not a valid web address.")
        elif typ == "kv":
            val = [{"k": k.strip(), "v": v.strip()}
                   for k, v in zip(form.getlist(name + "__k[]"), form.getlist(name + "__v[]"))
                   if k.strip() or v.strip()]
        elif typ in SINGLE_FILE:
            old = existing.get(key) if isinstance(existing.get(key), dict) else None
            val = old
            if old and old.get("f") in form.getlist("rm_" + key):
                val = None
            up = files.get("up_" + key)
            if up and up.filename:
                new = save_upload(up, f, errors)
                if new:
                    val = new
        elif typ in MULTI_FILE:
            old = [v for v in (existing.get(key) or []) if isinstance(v, dict)]
            removed = set(form.getlist("rm_" + key))
            val = [v for v in old if v.get("f") not in removed]
            for up in files.getlist("up_" + key):
                if up and up.filename:
                    new = save_upload(up, f, errors)
                    if new:
                        val.append(new)
        else:
            val = (form.get(name) or "").strip()
        if f.get("required") and val in ("", None, [], False):
            errors.append(f"{f['label']} is required.")
        data[key] = val
    return data, errors


def _pairs(field):
    from schema import option_pairs
    return option_pairs(field.get("options"))


def is_empty(val):
    return val in ("", None, [], {}, False)


# --------------------------------------------------------------------------- display
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(value):
    if not value:
        return ""
    try:
        d = datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return str(value)
    return f"{MONTHS[d.month - 1]} {d.year}"


def fmt_date_full(value):
    try:
        d = datetime.strptime(value[:10], "%Y-%m-%d").date()
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    except (ValueError, TypeError):
        return str(value or "")


def fmt_range(start, end, current):
    s, e = fmt_date(start), fmt_date(end)
    if current:
        e = "Present"
    if s and e:
        return f"{s} – {e}"
    return s or e or ""


def media_url(stored):
    return f"/media/{stored}"


def video_embed(url):
    m = re.match(r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([\w-]{6,15})", url or "")
    if m:
        return f"https://www.youtube-nocookie.com/embed/{m.group(1)}"
    m = re.match(r"https?://(?:www\.)?vimeo\.com/(\d+)", url or "")
    if m:
        return f"https://player.vimeo.com/video/{m.group(1)}"
    return ""


def _a(url, label=None):
    return Markup('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>').format(url, label or url)


def _file_link(v):
    ext = v["f"].rsplit(".", 1)[-1].lower()
    return Markup('<a class="filelink" href="{}" target="_blank" rel="noopener">{}</a>').format(
        media_url(v["f"]), v.get("n") or v["f"]) if ext else ""


def render_value(field, value, lookup=None):
    """HTML for one value, safe to put in a page."""
    typ = field["type"]
    if is_empty(value) and typ != "checkbox":
        return Markup("")
    if typ == "richtext":
        return Markup('<div class="rich">') + Markup(sanitize_html(value)) + Markup("</div>")
    if typ == "textarea":
        return Markup('<p class="pre">') + escape(value) + Markup("</p>")
    if typ in ("url",):
        u = clean_url(value)
        return _a(u, re.sub(r"^https?://(www\.)?", "", u).rstrip("/")) if u else Markup("")
    if typ == "videourl":
        u = clean_url(value)
        emb = video_embed(u)
        if emb:
            return Markup('<div class="video"><iframe src="{}" loading="lazy" allowfullscreen '
                          'referrerpolicy="no-referrer" title="Video"></iframe></div>').format(emb)
        return _a(u) if u else Markup("")
    if typ == "email":
        return _a("mailto:" + str(value), value)
    if typ == "phone":
        tel = re.sub(r"[^\d+]", "", str(value))
        return _a("tel:" + tel, value)
    if typ == "date":
        return escape(fmt_date_full(value))
    if typ == "checkbox":
        return Markup("Yes" if value else "No")
    if typ == "number":
        return escape(value)
    if typ in ("tags", "multiselect"):
        return Markup('<ul class="tags">') + Markup("").join(
            Markup("<li>{}</li>").format(t) for t in value) + Markup("</ul>")
    if typ == "list":
        return Markup("<ul>") + Markup("").join(Markup("<li>{}</li>").format(t) for t in value) + Markup("</ul>")
    if typ == "urllist":
        parts = []
        for u in [clean_url(x) for x in value if clean_url(x)]:
            emb = video_embed(u)
            parts.append(Markup('<div class="video"><iframe src="{}" loading="lazy" allowfullscreen '
                                'referrerpolicy="no-referrer" title="Video"></iframe></div>').format(emb)
                         if emb else Markup("<div>{}</div>").format(_a(u)))
        return Markup("").join(parts)
    if typ == "links":
        good = [l for l in value if isinstance(l, dict) and clean_url(l.get("url"))]
        return Markup('<ul class="linklist">') + Markup("").join(
            Markup("<li>{}</li>").format(_a(clean_url(l["url"]), l.get("label"))) for l in good) + Markup("</ul>") \
            if good else Markup("")
    if typ == "kv":
        return Markup('<dl class="kv">') + Markup("").join(
            Markup("<div><dt>{}</dt><dd>{}</dd></div>").format(r["k"], r["v"]) for r in value) + Markup("</dl>")
    if typ == "image" and isinstance(value, dict):
        return Markup('<img class="pic" src="{}" alt="{}" loading="lazy">').format(
            media_url(value["f"]), value.get("n", ""))
    if typ == "images":
        return Markup('<div class="gallery">') + Markup("").join(
            Markup('<a href="{0}" target="_blank" rel="noopener"><img src="{0}" alt="{1}" loading="lazy"></a>')
            .format(media_url(v["f"]), v.get("n", "")) for v in value) + Markup("</div>")
    if typ == "file" and isinstance(value, dict):
        return _file_link(value)
    if typ == "files":
        return Markup('<ul class="files">') + Markup("").join(
            Markup("<li>{}</li>").format(_file_link(v)) for v in value) + Markup("</ul>")
    if typ == "ref":
        return escape((lookup or {}).get(value, ""))
    return escape(value)


def plain_value(field, value, lookup=None):
    """Short plain-text form (used in card meta lines)."""
    typ = field["type"]
    if is_empty(value):
        return ""
    if typ == "date":
        return fmt_date(value)
    if typ in ("tags", "multiselect", "list"):
        return ", ".join(value)
    if typ == "ref":
        return (lookup or {}).get(value, "")
    if typ == "checkbox":
        return field["label"] if value else ""
    if typ in ("image", "file", "images", "files", "links", "kv", "urllist"):
        return ""
    return str(value)
