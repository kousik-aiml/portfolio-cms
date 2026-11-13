"""Public website routes."""
from flask import Blueprint, abort, redirect, render_template

import db
import present
from schema import get_section, item_title

bp = Blueprint("public", __name__)


def render_site(preview=False):
    prefix = "/admin/preview" if preview else ""
    profile, sections = present.page_sections(preview, prefix)
    return render_template(
        "public/index.html", hero=present.hero(profile), sections=sections, preview=preview,
        prefix=prefix, resume_url=present.default_resume_link(preview),
        nav=[(s["key"], s["title"]) for s in sections],
    )


def render_detail(key, uid, preview=False):
    sec = get_section(key)
    item = db.get_item_by_uid(uid)
    if not sec or not item or item["section"] != key or key in present.NO_DETAIL:
        abort(404)
    if not preview:
        if item["status"] != "published" or not item["visible"] or item["published_data"] is None:
            abort(404)
        data = item["published_data"]
    else:
        data = item["data"]
    prefix = "/admin/preview" if preview else ""
    lookup = present.lookup_names()
    profile = present.get_profile(preview)
    return render_template(
        "public/detail.html", sec=sec, title=item_title(sec, data), rows=present.detail_rows(sec, data, lookup),
        card=present.build_card(sec, item, data, lookup, preview, prefix), hero=present.hero(profile),
        preview=preview, prefix=prefix, resume_url=present.default_resume_link(preview),
        nav=[],
    )


@bp.route("/")
def index():
    return render_site(False)


@bp.route("/s/<key>/<uid>")
def detail(key, uid):
    return render_detail(key, uid, False)


@bp.route("/resume")
def resume():
    url = present.default_resume_link(False)
    if not url:
        abort(404)
    return redirect(url)
