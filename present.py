"""Builds the view-models the public site (and the admin preview) renders."""
import re

import db
from forms import clean_url, fmt_range, is_empty, media_url, plain_value, render_value
from sanitize import strip_tags
from schema import get_section, item_title

SHORT_TYPES = {"text", "number", "date", "email", "phone", "url", "select", "checkbox", "multiselect", "tags"}
NO_DETAIL = {"skills", "resumes", "skill_categories"}


# --------------------------------------------------------------------------- profile
def get_profile(preview=False):
    """{key: value} of the fields that are visible (published copy unless previewing)."""
    out = {}
    for r in db.get_db().execute("SELECT * FROM profile_fields"):
        vis = r["visible"] if preview else r["published_visible"]
        raw = r["value"] if preview else r["published_value"]
        if vis:
            out[r["key"]] = db.jload(raw, "")
    return out


def get_profile_all():
    """Working copy for the admin form: {key: (value, visible)}."""
    return {r["key"]: (db.jload(r["value"], ""), bool(r["visible"]))
            for r in db.get_db().execute("SELECT * FROM profile_fields")}


# --------------------------------------------------------------------------- items
def lookup_names():
    return {i["uid"]: i["data"].get("name", "") for i in db.list_items("skill_categories")}


def visible_items(section_key, preview=False):
    out = []
    for it in db.list_items(section_key):
        if not it["visible"]:
            continue
        if preview:
            out.append((it, it["data"]))
        elif it["status"] == "published" and it["published_data"] is not None:
            out.append((it, it["published_data"]))
    return out


def _custom_public(sec):
    return {f["key"]: f for f in sec["fields"] if f.get("custom") and f.get("show_public")}


def build_card(sec, item, data, lookup, preview=False, prefix=""):
    fmap = {f["key"]: f for f in sec["fields"]}

    def plain(key):
        f = fmap.get(key)
        return plain_value(f, data.get(key), lookup) if f else ""

    card = {
        "uid": item["uid"], "title": item_title(sec, data), "draft": item["status"] != "published",
        "dirty": item.get("dirty"), "section": sec["key"],
    }
    card["subtitle"] = " · ".join(p for p in (plain(k) for k in sec.get("subtitle", [])) if p)
    if sec.get("range"):
        s, e, cur = sec["range"]
        card["range"] = fmt_range(data.get(s), data.get(e), data.get(cur) if cur else False)
    else:
        card["range"] = ""
    card["meta"] = [p for p in (plain(k) for k in sec.get("meta", [])) if p]
    summary = ""
    skey = sec.get("summary")
    if skey and not is_empty(data.get(skey)):
        v = data[skey]
        summary = ("; ".join(v[:3]) if isinstance(v, list) else strip_tags(v))
        if len(summary) > 220:
            summary = summary[:217].rsplit(" ", 1)[0] + "…"
    card["summary"] = summary
    card["tags"] = list(data.get(sec.get("tags") or "", []) or [])[:8]
    img = data.get(sec.get("image") or "")
    if isinstance(img, list):
        img = img[0] if img else None
    card["image"] = media_url(img["f"]) if isinstance(img, dict) and img.get("f") and \
        img["f"].rsplit(".", 1)[-1].lower() in ("png", "jpg", "jpeg", "gif", "webp") else ""
    card["badge"] = plain(sec["badge"]) if sec.get("badge") else ""
    links = []
    for k in sec.get("links", []):
        u = clean_url(data.get(k))
        if u:
            links.append((fmap[k]["label"], u))
    card["links"] = links
    p = data.get(sec.get("progress") or "")
    card["progress"] = int(p) if isinstance(p, (int, float)) and not isinstance(p, bool) else None
    if card["progress"] is not None:
        card["progress"] = max(0, min(100, card["progress"]))
    extras = []
    for key, f in _custom_public(sec).items():
        if f["type"] in SHORT_TYPES and not is_empty(data.get(key)):
            extras.append((f["label"], plain_value(f, data.get(key), lookup)))
    card["extras"] = extras
    card["detail_url"] = (f"{prefix}/s/{sec['key']}/{item['uid']}"
                          if sec["key"] not in NO_DETAIL else "")
    if sec["key"] == "resumes":
        f = data.get("file")
        if isinstance(f, dict) and f.get("f"):
            card["links"] = [("View", media_url(f["f"])), ("Download", media_url(f["f"]) + "?dl=1")]
        if item["uid"] == db.get_setting("default_resume"):
            card["badge"] = "Default"
    return card


def group_cards(sec, pairs, lookup, preview=False, prefix=""):
    """[(heading|None, [cards])] according to the section's grouping rule."""
    cards = [(build_card(sec, it, d, lookup, preview, prefix), d) for it, d in pairs]
    gb = sec.get("group_by")
    if not gb:
        return [(None, [c for c, _ in cards])]
    groups, order = {}, []
    if gb == "category":
        for c in db.list_items("skill_categories"):
            order.append((c["uid"], c["data"].get("name", "")))
        order.append(("", "Other"))
    else:
        for name in sec.get("group_order", []):
            order.append((name, name))
        order.append(("", "Other"))
    for card, d in cards:
        k = d.get(gb) or ""
        if k not in [o[0] for o in order]:
            order.insert(len(order) - 1, (k, k))
        groups.setdefault(k, []).append(card)
    return [(label, groups[k]) for k, label in order if groups.get(k)]


def profile_blocks(profile, defs):
    """Ordered (label, html) pairs for the 'about' section."""
    skip = {"full_name", "first_name", "last_name", "profile_picture", "headline", "short_intro"}
    contact = {"email", "phone", "whatsapp", "website", "linkedin", "github", "social_links"}
    about, contact_rows = [], []
    for f in defs:
        key = f["key"]
        if key in skip or key not in profile or is_empty(profile[key]):
            continue
        if f.get("custom") and not f.get("show_public"):
            continue
        html = render_value(f, profile[key])
        if not str(html):
            continue
        (contact_rows if key in contact or f.get("group") == "Contact & links" else about).append(
            (f["label"], html, f["type"], key))
    return about, contact_rows


def page_sections(preview=False, prefix=""):
    """Everything the single-page site needs, in the owner's chosen order."""
    from schema import profile_fields
    profile = get_profile(preview)
    defs = profile_fields()
    about_rows, contact_rows = profile_blocks(profile, defs)
    lookup = lookup_names()
    out = []
    for s in db.site_sections(visible_only=True):
        entry = {"key": s["key"], "title": s["title"], "intro": s["intro"], "layout": s["layout"],
                 "groups": [], "rows": []}
        if s["key"] == "about" and s["kind"] == "profile":
            entry["kind"] = "about"
            entry["rows"] = about_rows
            if not about_rows:
                continue
        elif s["key"] == "contact" and s["kind"] == "profile":
            entry["kind"] = "contact"
            entry["rows"] = contact_rows
            if not contact_rows:
                continue
        else:
            sec = get_section(s["key"])
            if not sec:
                continue
            pairs = visible_items(s["key"], preview)
            if not pairs:
                continue
            entry["kind"] = "items"
            entry["groups"] = group_cards(sec, pairs, lookup, preview, prefix)
        out.append(entry)
    return profile, out


def detail_rows(sec, data, lookup):
    rows = []
    title_keys = set(sec.get("title_keys", []))
    for f in sec["fields"]:
        if f.get("custom") and not f.get("show_public"):
            continue
        if f["key"] in title_keys and f["type"] in ("text", "combo"):
            continue
        v = data.get(f["key"])
        if is_empty(v) and f["type"] != "checkbox":
            continue
        if f["type"] == "checkbox" and not v:
            continue
        html = render_value(f, v, lookup)
        if str(html):
            rows.append((f["label"], html, f["type"]))
    return rows


def hero(profile):
    name = profile.get("full_name") or " ".join(
        p for p in (profile.get("first_name"), profile.get("last_name")) if p)
    pic = profile.get("profile_picture")
    return {
        "name": name, "headline": profile.get("headline", ""),
        "intro": profile.get("short_intro", ""),
        "picture": media_url(pic["f"]) if isinstance(pic, dict) and pic.get("f") else "",
        "location": ", ".join(p for p in (profile.get("city"), profile.get("country")) if p),
        "email": profile.get("email", ""),
        "github": clean_url(profile.get("github")), "linkedin": clean_url(profile.get("linkedin")),
    }


def default_resume_link(preview=False):
    uid = db.get_setting("default_resume")
    candidates = []
    if uid:
        it = db.get_item_by_uid(uid)
        if it:
            candidates.append(it)
    if not candidates:
        candidates = [i for i in db.list_items("resumes")]
    for it in candidates:
        if not it["visible"]:
            continue
        data = it["data"] if preview else (it["published_data"] if it["status"] == "published" else None)
        f = (data or {}).get("file")
        if isinstance(f, dict) and f.get("f"):
            return media_url(f["f"])
    return ""
