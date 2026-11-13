"""Field definitions for every kind of content.

This is the *only* place that knows what the built-in sections look like, and it
is only used to build forms and public pages. Owner-defined custom fields and
custom sections come from the database and are merged in by ``get_section``.
"""
import re

from db import get_db, jload, list_items


def F(key, label, type="text", **kw):
    d = {"key": key, "label": label, "type": type}
    d.update(kw)
    return d


# --------------------------------------------------------------------------- option lists
EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Internship", "Contract", "Freelance",
                    "Self-employed", "Apprenticeship", "Volunteer", "Other"]
PROFICIENCY = ["Beginner", "Basic", "Intermediate", "Advanced", "Expert"]
SKILL_STATUS = ["Planned", "Currently learning", "Practising", "Comfortable", "Mastered"]
PROJECT_STATUS = ["Planned", "In progress", "Completed", "On hold", "Archived"]
LEARNING_KINDS = ["Current learning topic", "Completed topic", "Learning resource", "Book",
                  "Course", "Study note", "Practice exercise", "Learning milestone",
                  "Future learning goal"]
LEARNING_STATUS = ["Planned", "In progress", "Completed", "Paused"]
ACHIEVEMENT_TYPES = ["Award", "Competition", "Hackathon", "Workshop", "Seminar", "Publication",
                     "Research work", "Volunteer activity", "Professional achievement",
                     "Personal milestone"]

# Every record also gets these two (requirement: "upload attachments" / "add external links").
COMMON_FIELDS = [
    F("ext_links", "External links", "links", help="Any related links (label + URL)."),
    F("attachments", "Attachments / supporting documents", "files",
      help="PDF, images, Office files, zip ... (max size is set by the server)."),
]

# --------------------------------------------------------------------------- built-in sections
SECTIONS = {
    "education": {
        "title": "Education", "singular": "education record", "icon": "🎓",
        "fields": [
            F("institution", "Institution name", required=True),
            F("degree", "Degree"),
            F("specialization", "Specialization"),
            F("duration", "Course duration", placeholder="e.g. 4 years"),
            F("start_date", "Start date", "date"),
            F("end_date", "End date", "date"),
            F("is_current", "Currently studying here", "checkbox"),
            F("grade", "Grade / CGPA", placeholder="optional"),
            F("subjects", "Relevant subjects", "tags", help="Comma separated."),
            F("description", "Description", "richtext"),
            F("logo", "Institution logo", "image"),
        ],
        "title_keys": ["degree", "specialization"], "fallback_title": "institution",
        "subtitle": ["institution"], "range": ("start_date", "end_date", "is_current"),
        "meta": ["duration", "grade"], "summary": "description", "tags": "subjects", "image": "logo",
        "sort_key": "start_date", "layout": "timeline",
    },
    "experience": {
        "title": "Experience", "singular": "employment record", "icon": "💼",
        "fields": [
            F("company", "Company name", required=True),
            F("job_title", "Job title", required=True),
            F("employment_type", "Employment type", "combo", options=EMPLOYMENT_TYPES),
            F("department", "Department"),
            F("location", "Location"),
            F("start_date", "Start date", "date"),
            F("end_date", "End date", "date"),
            F("is_current", "I currently work here", "checkbox"),
            F("responsibilities", "Responsibilities", "list"),
            F("achievements", "Achievements", "list"),
            F("skills_used", "Skills used", "tags", help="Comma separated."),
            F("logo", "Company logo", "image"),
        ],
        "title_keys": ["job_title"], "fallback_title": "company",
        "subtitle": ["company", "location"], "range": ("start_date", "end_date", "is_current"),
        "meta": ["employment_type", "department"], "summary": "responsibilities",
        "tags": "skills_used", "image": "logo", "sort_key": "start_date", "layout": "timeline",
    },
    "skill_categories": {
        "title": "Skill categories", "singular": "skill category", "icon": "🗂️", "support": True,
        "common": False,
        "fields": [
            F("name", "Category name", required=True, placeholder="e.g. Machine Learning"),
            F("description", "Description", "textarea"),
            F("icon", "Icon (emoji or short text)", maxlength=8),
        ],
        "title_keys": ["name"], "subtitle": [], "meta": [],
    },
    "skills": {
        "title": "Skills", "singular": "skill", "icon": "🛠️",
        "fields": [
            F("name", "Skill name", required=True),
            F("category", "Category", "ref", ref="skill_categories",
              help="Create unlimited categories under Skills → Manage categories."),
            F("proficiency", "Proficiency label", "combo", options=PROFICIENCY,
              help="A word, not a percentage. Pick one or type your own."),
            F("learning_status", "Learning status", "select", options=SKILL_STATUS),
            F("years", "Years of experience", "number", placeholder="optional", step="0.5"),
            F("description", "Description", "textarea"),
            F("icon", "Icon (emoji or short text)", maxlength=8),
            F("icon_image", "Icon image", "image"),
        ],
        "title_keys": ["name"], "subtitle": ["proficiency"], "meta": [], "group_by": "category",
        "layout": "cards",
    },
    "certifications": {
        "title": "Certifications & Courses", "singular": "certification", "icon": "📜",
        "fields": [
            F("title", "Certificate title", required=True),
            F("organization", "Issuing organization"),
            F("provider", "Course provider / platform"),
            F("completion_date", "Completion date", "date"),
            F("expiry_date", "Expiry date", "date", help="Optional."),
            F("credential_id", "Credential ID", placeholder="optional"),
            F("verify_url", "Credential verification URL", "url"),
            F("certificate_file", "Certificate image or PDF", "file"),
            F("description", "Description", "richtext"),
            F("skills_learned", "Skills learned", "tags", help="Comma separated."),
        ],
        "title_keys": ["title"], "subtitle": ["organization", "provider"],
        "meta": ["completion_date", "expiry_date", "credential_id"], "summary": "description",
        "tags": "skills_learned", "image": "certificate_file", "links": ["verify_url"],
        "sort_key": "completion_date", "layout": "cards",
    },
    "projects": {
        "title": "Projects", "singular": "project", "icon": "🚀",
        "fields": [
            F("name", "Project name", required=True),
            F("category", "Project category", "combo", options=[],
              placeholder="e.g. Machine Learning, Web App"),
            F("status", "Project status", "select", options=PROJECT_STATUS),
            F("short_description", "Short description", "textarea"),
            F("detailed_explanation", "Detailed explanation", "richtext"),
            F("problem", "Problem statement", "richtext"),
            F("solution", "Solution", "richtext"),
            F("technologies", "Technologies", "tags", help="Comma separated."),
            F("features", "Features", "list"),
            F("start_date", "Start date", "date"),
            F("completion_date", "Completion date", "date"),
            F("github_url", "GitHub repository", "url"),
            F("demo_url", "Live demo", "url"),
            F("images", "Project images", "images"),
            F("videos", "Videos (links)", "urllist", help="YouTube, Vimeo or any video link."),
            F("documentation", "Documentation files", "files"),
            F("challenges", "Challenges", "richtext"),
            F("learning_outcomes", "Learning outcomes", "richtext"),
            F("metrics", "Evaluation metrics", "kv", help="Optional, e.g. Accuracy → 94%."),
        ],
        "title_keys": ["name"], "subtitle": ["category"], "range": ("start_date", "completion_date", None),
        "meta": [], "summary": "short_description", "tags": "technologies", "image": "images",
        "badge": "status", "links": ["github_url", "demo_url"], "sort_key": "start_date",
        "layout": "cards",
    },
    "learning": {
        "title": "Learning Journey", "singular": "learning entry", "icon": "📚",
        "fields": [
            F("title", "Title", required=True),
            F("kind", "Type", "select", options=LEARNING_KINDS, required=True),
            F("status", "Status", "select", options=LEARNING_STATUS),
            F("progress", "Progress (%)", "number", placeholder="optional, 0-100", min="0", max="100"),
            F("provider", "Author / provider / platform"),
            F("resource_url", "Resource link", "url"),
            F("start_date", "Start date", "date"),
            F("end_date", "Completed / target date", "date"),
            F("description", "Notes / description", "richtext"),
            F("tags", "Topics", "tags", help="Comma separated."),
        ],
        "title_keys": ["title"], "subtitle": ["provider"], "range": ("start_date", "end_date", None),
        "meta": ["status"], "summary": "description", "tags": "tags", "badge": "kind",
        "links": ["resource_url"], "group_by": "kind", "group_order": LEARNING_KINDS,
        "progress": "progress", "sort_key": "start_date", "layout": "cards",
    },
    "achievements": {
        "title": "Achievements & Activities", "singular": "achievement", "icon": "🏆",
        "fields": [
            F("title", "Title", required=True),
            F("type", "Type", "select", options=ACHIEVEMENT_TYPES, required=True),
            F("organization", "Organisation / event"),
            F("date", "Date", "date"),
            F("result", "Result / rank / role"),
            F("description", "Description", "richtext"),
            F("url", "Link", "url"),
            F("image", "Image", "image"),
        ],
        "title_keys": ["title"], "subtitle": ["organization"], "meta": ["result", "date"],
        "summary": "description", "image": "image", "links": ["url"], "group_by": "type",
        "group_order": ACHIEVEMENT_TYPES, "sort_key": "date", "layout": "cards",
    },
    "resumes": {
        "title": "Resume", "singular": "resume version", "icon": "📄", "common": False,
        "fields": [
            F("label", "Version name", required=True, placeholder="e.g. Data Science 2026"),
            F("file", "Resume (PDF)", "file", required=True, exts="pdf"),
            F("details", "Details / notes", "textarea"),
            F("updated_on", "Last updated", "date"),
        ],
        "title_keys": ["label"], "subtitle": [], "meta": ["updated_on"], "layout": "list",
    },
}

# Template used for sections the owner creates in the admin panel.
CUSTOM_SECTION = {
    "singular": "entry", "icon": "✨",
    "fields": [
        F("title", "Title", required=True),
        F("subtitle", "Subtitle"),
        F("date", "Date", "date"),
        F("description", "Description", "richtext"),
        F("image", "Image", "image"),
        F("tags", "Tags", "tags", help="Comma separated."),
    ],
    "title_keys": ["title"], "subtitle": ["subtitle"], "meta": ["date"], "summary": "description",
    "tags": "tags", "image": "image", "sort_key": "date", "layout": "cards",
}

# Rows created in site_sections on first run (position = order on the website).
DEFAULT_SITE_SECTIONS = [
    ("about", "About", "profile", "cards"),
    ("education", "Education", "builtin", "timeline"),
    ("experience", "Experience", "builtin", "timeline"),
    ("skills", "Skills", "builtin", "cards"),
    ("projects", "Projects", "builtin", "cards"),
    ("certifications", "Certifications & Courses", "builtin", "cards"),
    ("learning", "Learning Journey", "builtin", "cards"),
    ("achievements", "Achievements & Activities", "builtin", "cards"),
    ("resumes", "Resume", "builtin", "list"),
    ("contact", "Contact", "profile", "cards"),
]

RESERVED_SLUGS = set(SECTIONS) | {
    "about", "contact", "profile", "admin", "media", "static", "resume", "item", "preview",
    "login", "logout", "settings", "data", "sections", "custom", "home", "index",
}

# --------------------------------------------------------------------------- profile fields
PROFILE_GROUPS = ["Identity", "About you", "Personal details", "Contact & links"]
PROFILE_FIELDS = [
    F("full_name", "Full name", group="Identity"),
    F("first_name", "First name", group="Identity"),
    F("last_name", "Last name", group="Identity"),
    F("profile_picture", "Profile picture", "image", group="Identity"),
    F("headline", "Professional headline", group="Identity", placeholder="e.g. Data Scientist & ML Engineer"),
    F("short_intro", "Short introduction", "textarea", group="About you"),
    F("biography", "Detailed biography", "richtext", group="About you"),
    F("career_objective", "Career objective", "textarea", group="About you"),
    F("professional_summary", "Professional summary", "richtext", group="About you"),
    F("date_of_birth", "Date of birth", "date", group="Personal details", default_hidden=True),
    F("nationality", "Nationality", group="Personal details"),
    F("city", "Current city", group="Personal details"),
    F("country", "Current country", group="Personal details"),
    F("interests", "Personal interests", "tags", group="Personal details", help="Comma separated."),
    F("hobbies", "Hobbies", "tags", group="Personal details", help="Comma separated."),
    F("languages", "Languages known", "tags", group="Personal details",
      help="Comma separated, e.g. English (fluent), Hindi (native)."),
    F("email", "Email address", "email", group="Contact & links"),
    F("phone", "Phone number", "phone", group="Contact & links"),
    F("whatsapp", "WhatsApp number", "phone", group="Contact & links"),
    F("website", "Professional website", "url", group="Contact & links"),
    F("linkedin", "LinkedIn URL", "url", group="Contact & links"),
    F("github", "GitHub URL", "url", group="Contact & links"),
    F("social_links", "Other social media", "links", group="Contact & links"),
]

CUSTOM_TYPES = [
    ("text", "Short text"), ("textarea", "Long text"), ("number", "Number"), ("date", "Date"),
    ("email", "Email"), ("phone", "Phone"), ("url", "URL"), ("image", "Image"),
    ("file", "PDF or file"), ("videourl", "Video URL"), ("select", "Dropdown"),
    ("multiselect", "Multiple selection"), ("checkbox", "Checkbox"), ("richtext", "Rich text"),
    ("list", "Repeatable list"),
]
CUSTOM_TYPE_KEYS = {k for k, _ in CUSTOM_TYPES}


# --------------------------------------------------------------------------- helpers
def slugify(text, fallback="field"):
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s[:40] or fallback


def custom_field_defs(target):
    rows = get_db().execute(
        "SELECT * FROM custom_fields WHERE target=? ORDER BY position, id", (target,)
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "key": "cf_" + r["key"], "label": r["label"], "type": r["type"],
            "options": jload(r["options"], []) or [], "help": r["help"], "custom": True,
            "def_id": r["id"], "show_public": bool(r["show_public"]),
        })
    return out


def _resolve_refs(fields):
    for f in fields:
        if f["type"] == "ref":
            f = f  # options injected below
            f["options"] = [
                (i["uid"], i["data"].get("name") or "(unnamed)") for i in list_items(f["ref"])
            ]
    return fields


def _project_categories(fields):
    """Suggest categories already used by other projects."""
    used = []
    for it in list_items("projects"):
        c = (it["data"].get("category") or "").strip()
        if c and c not in used:
            used.append(c)
    for f in fields:
        if f["key"] == "category" and f["type"] == "combo":
            f["options"] = used
    return fields


def get_section(key):
    """Full definition of a section (built-in or custom), including custom fields."""
    if key in SECTIONS:
        base = SECTIONS[key]
        row = get_db().execute("SELECT * FROM site_sections WHERE key=?", (key,)).fetchone()
        sec = {k: v for k, v in base.items() if k != "fields"}
        sec["key"] = key
        sec["builtin"] = True
        sec["title"] = row["title"] if row else base["title"]
        sec["intro"] = row["intro"] if row else ""
        sec["layout"] = row["layout"] if row else base.get("layout", "cards")
        fields = [dict(f) for f in base["fields"]]
        if base.get("common", True):
            fields += [dict(f) for f in COMMON_FIELDS]
    else:
        row = get_db().execute(
            "SELECT * FROM site_sections WHERE key=? AND kind='custom'", (key,)
        ).fetchone()
        if not row:
            return None
        base = CUSTOM_SECTION
        sec = {k: v for k, v in base.items() if k != "fields"}
        sec.update(key=key, builtin=False, title=row["title"], intro=row["intro"], layout=row["layout"])
        fields = [dict(f) for f in base["fields"]] + [dict(f) for f in COMMON_FIELDS]
    fields = _resolve_refs(fields)
    if key == "projects":
        fields = _project_categories(fields)
    fields += custom_field_defs(key)
    sec["fields"] = fields
    return sec


def profile_fields():
    return [dict(f) for f in PROFILE_FIELDS] + custom_field_defs("profile")


def all_targets():
    """Everything a custom field can be attached to: [(key, label)]."""
    targets = [("profile", "Profile")]
    for s in get_db().execute("SELECT key,title,kind FROM site_sections ORDER BY position"):
        if s["kind"] == "profile":
            continue
        targets.append((s["key"], s["title"]))
    return targets


def option_pairs(options):
    pairs = []
    for o in options or []:
        if isinstance(o, (list, tuple)):
            pairs.append((o[0], o[1] if len(o) > 1 else o[0]))
        else:
            pairs.append((o, o))
    return pairs


def item_title(sec, data):
    parts = [str(data.get(k)).strip() for k in sec.get("title_keys", []) if data.get(k)]
    title = " — ".join(parts)
    if not title and sec.get("fallback_title"):
        title = str(data.get(sec["fallback_title"]) or "")
    return title or "Untitled"
