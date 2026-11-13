"""Sample content so the site looks complete on first run. Replace or delete it all in the admin panel."""
import db
from schema import DEFAULT_SITE_SECTIONS, PROFILE_FIELDS

SAMPLE_PROFILE = {
    "full_name": "Alex Sample", "first_name": "Alex", "last_name": "Sample",
    "headline": "Data Scientist & Machine Learning Engineer",
    "short_intro": "I turn messy data into clear decisions and build ML systems that hold up in the real world.",
    "biography": "<p>This is <strong>sample text</strong>. Open the admin panel, go to <em>Profile</em> and replace "
                 "everything here with your own story.</p><p>Every field can be shown or hidden on the public site.</p>",
    "career_objective": "To work on impactful data products while continuing to learn.",
    "professional_summary": "<p>Replace this with a short professional summary.</p>",
    "nationality": "Indian", "city": "Bengaluru", "country": "India",
    "interests": ["Machine learning", "Open source", "Data storytelling"],
    "hobbies": ["Chess", "Trekking"],
    "languages": ["English (fluent)", "Hindi (native)"],
    "email": "hello@example.com", "github": "https://github.com/example",
    "linkedin": "https://www.linkedin.com/in/example",
}
HIDDEN_BY_DEFAULT = {"date_of_birth", "phone", "whatsapp"}

SAMPLE_ITEMS = {
    "skill_categories": [
        {"name": "Programming Languages", "icon": "💻"},
        {"name": "Machine Learning", "icon": "🤖"},
        {"name": "Data Visualization", "icon": "📊"},
    ],
    "education": [
        {"institution": "Sample University", "degree": "B.Tech", "specialization": "Computer Science",
         "duration": "4 years", "start_date": "2020-08-01", "end_date": "2024-05-01", "grade": "8.6 CGPA",
         "subjects": ["Algorithms", "Statistics", "Databases"],
         "description": "<p>Sample education record. Edit or delete it.</p>"},
    ],
    "experience": [
        {"company": "Example Analytics", "job_title": "Data Science Intern", "employment_type": "Internship",
         "location": "Remote", "start_date": "2023-06-01", "end_date": "2023-09-01",
         "responsibilities": ["Built churn-prediction models", "Automated weekly reporting"],
         "achievements": ["Cut report preparation time by 70%"], "skills_used": ["Python", "SQL", "scikit-learn"]},
    ],
    "projects": [
        {"name": "Sample ML Project", "category": "Machine Learning", "status": "Completed",
         "short_description": "A placeholder project showing how a portfolio card looks.",
         "technologies": ["Python", "PyTorch", "Flask"], "features": ["Training pipeline", "REST API"],
         "start_date": "2024-01-01", "completion_date": "2024-03-01",
         "problem": "<p>Describe the problem here.</p>", "solution": "<p>Describe your solution here.</p>",
         "metrics": [{"k": "Accuracy", "v": "94%"}]},
    ],
    "certifications": [
        {"title": "Sample Certificate", "organization": "Example Academy", "provider": "Coursera",
         "completion_date": "2024-02-01", "skills_learned": ["Deep learning"]},
    ],
    "learning": [
        {"title": "Reinforcement learning", "kind": "Current learning topic", "status": "In progress", "progress": 40},
        {"title": "Designing Data-Intensive Applications", "kind": "Book", "status": "Planned"},
        {"title": "Learn Rust", "kind": "Future learning goal", "status": "Planned"},
    ],
    "achievements": [
        {"title": "Sample Hackathon Finalist", "type": "Hackathon", "organization": "Example Hack",
         "date": "2023-11-01", "result": "Top 10"},
    ],
}

SAMPLE_SKILLS = [
    ("Python", "Programming Languages", "Advanced", "Practising", 3),
    ("SQL", "Programming Languages", "Intermediate", "Comfortable", 2),
    ("scikit-learn", "Machine Learning", "Intermediate", "Practising", 2),
    ("PyTorch", "Machine Learning", "Beginner", "Currently learning", 1),
    ("Matplotlib", "Data Visualization", "Intermediate", "Comfortable", 2),
]


def seed_if_empty():
    if db.get_setting("seeded"):
        return
    conn = db.get_db()
    for key, label, kind, layout in DEFAULT_SITE_SECTIONS:
        pos = conn.execute("SELECT COUNT(*) c FROM site_sections").fetchone()["c"]
        conn.execute(
            "INSERT OR IGNORE INTO site_sections(key,title,kind,position,layout) VALUES(?,?,?,?,?)",
            (key, label, kind, pos, layout))
    for f in PROFILE_FIELDS:
        val = SAMPLE_PROFILE.get(f["key"], [] if f["type"] in ("tags", "links") else "")
        vis = 0 if f["key"] in HIDDEN_BY_DEFAULT else 1
        text = db.jdump(val)
        conn.execute(
            "INSERT OR IGNORE INTO profile_fields(key,value,visible,published_value,published_visible) VALUES(?,?,?,?,?)",
            (f["key"], text, vis, text, vis))
    cat_ids = {}
    for section, rows in SAMPLE_ITEMS.items():
        for row in rows:
            uid = db.new_uid()
            db.create_item(section, row, publish=True, uid=uid)
            if section == "skill_categories":
                cat_ids[row["name"]] = uid
    for name, cat, prof, status, years in SAMPLE_SKILLS:
        db.create_item("skills", {"name": name, "category": cat_ids[cat], "proficiency": prof,
                                  "learning_status": status, "years": years}, publish=True)
    db.set_setting("site_title", "Alex Sample — Portfolio")
    db.set_setting("tagline", "")
    db.set_setting("accent", "#4f46e5")
    db.set_setting("footer", "")
    db.set_setting("seeded", "1")
    conn.commit()
