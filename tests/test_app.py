import io, json, os, re, sys, tempfile, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(str(tmp_path))
    app.config["TESTING"] = True
    c = app.test_client()
    return c


def token(c, path="/admin/login"):
    html = c.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    return m.group(1)


def post(c, path, data=None, **kw):
    t = token(c, kw.pop("tokpath", "/admin/login" if "portfolio_session" not in str(c._cookies) else "/admin/"))
    data = dict(data or {}); data["csrf_token"] = t
    return c.post(path, data=data, **kw)


@pytest.fixture()
def admin(client):
    c = client
    r = c.get("/admin/", follow_redirects=False)
    assert r.status_code == 302 and "/admin/setup" in r.location
    t = token(c, "/admin/setup")
    r = c.post("/admin/setup", data={"csrf_token": t, "password": "supersecret1", "password2": "supersecret1"})
    assert r.status_code == 302
    return c


def tok(c):
    return token(c, "/admin/data")


def test_public_site_has_sample_content(client):
    html = client.get("/").get_data(as_text=True)
    assert "Alex Sample" in html and "Sample ML Project" in html
    assert "hello@example.com" in html
    assert "98765" not in html  # hidden phone not leaked


def test_all_admin_pages_render(admin):
    for p in ["/admin/", "/admin/profile", "/admin/sections", "/admin/fields", "/admin/data", "/admin/settings",
              "/admin/preview/"] + [f"/admin/s/{k}" for k in
              ["education", "experience", "skills", "skill_categories", "certifications", "projects",
               "learning", "achievements", "resumes"]] + \
             [f"/admin/s/{k}/new" for k in ["education", "experience", "skills", "skill_categories", "certifications",
              "projects", "learning", "achievements", "resumes"]]:
        r = admin.get(p)
        assert r.status_code == 200, (p, r.status_code, r.get_data(as_text=True)[:300])


def test_csrf_required(admin):
    r = admin.post("/admin/settings", data={"form": "site"})
    assert r.status_code == 400


def test_login_logout(client):
    t = token(client, "/admin/setup")
    client.post("/admin/setup", data={"csrf_token": t, "password": "supersecret1", "password2": "supersecret1"})
    client.post("/admin/logout", data={"csrf_token": tok(client)})
    assert client.get("/admin/").status_code == 302
    t = token(client)
    r = client.post("/admin/login", data={"csrf_token": t, "password": "bad"})
    assert r.status_code == 200 and "Wrong password" in r.get_data(as_text=True)
    r = client.post("/admin/login", data={"csrf_token": token(client), "password": "supersecret1"})
    assert r.status_code == 302


def test_draft_publish_hide_delete_flow(admin):
    c = admin
    r = c.post("/admin/s/education/new", data={"csrf_token": tok(c), "f_institution": "Draft Uni", "f_degree": "MSc",
                                                "visible": "1", "action": "draft"})
    assert r.status_code == 302
    assert "Draft Uni" not in c.get("/").get_data(as_text=True)
    assert "Draft Uni" in c.get("/admin/preview/").get_data(as_text=True)
    lst = c.get("/admin/s/education").get_data(as_text=True)
    iid = int(re.findall(r"/admin/i/(\d+)/edit", lst)[-1])
    c.post(f"/admin/i/{iid}/do/publish", data={"csrf_token": tok(c)})
    assert "Draft Uni" in c.get("/").get_data(as_text=True)
    # edit without publishing keeps the live version
    c.post(f"/admin/i/{iid}/edit", data={"csrf_token": tok(c), "f_institution": "Changed Uni", "visible": "1", "action": "draft"})
    live = c.get("/").get_data(as_text=True)
    assert "Draft Uni" in live and "Changed Uni" not in live
    assert "Unpublished edits" in c.get("/admin/s/education").get_data(as_text=True)
    c.post(f"/admin/i/{iid}/edit", data={"csrf_token": tok(c), "f_institution": "Changed Uni", "visible": "1", "action": "publish"})
    assert "Changed Uni" in c.get("/").get_data(as_text=True)
    c.post(f"/admin/i/{iid}/do/hide", data={"csrf_token": tok(c)})
    assert "Changed Uni" not in c.get("/").get_data(as_text=True)
    # delete needs confirmation
    assert c.post(f"/admin/i/{iid}/delete", data={"csrf_token": tok(c)}).status_code == 400
    assert c.get(f"/admin/i/{iid}/delete").status_code == 200
    assert c.post(f"/admin/i/{iid}/delete", data={"csrf_token": tok(c), "confirm": "yes"}).status_code == 302
    assert c.get(f"/admin/i/{iid}/edit").status_code == 404


def test_profile_visibility_and_publish(admin):
    c = admin
    data = {"csrf_token": tok(c), "f_full_name": "Jane Doe", "vis_full_name": "1", "f_headline": "Secret headline",
            "f_email": "jane@example.org", "vis_email": "1", "f_phone": "+1 555 0100", "action": "draft"}
    c.post("/admin/profile", data=data)
    assert "Jane Doe" not in c.get("/").get_data(as_text=True)  # draft only
    data["csrf_token"] = tok(c); data["action"] = "publish"
    c.post("/admin/profile", data=data)
    html = c.get("/").get_data(as_text=True)
    assert "Jane Doe" in html and "jane@example.org" in html
    assert "Secret headline" not in html and "555 0100" not in html  # not ticked -> hidden


def test_custom_field_on_profile_and_education(admin):
    c = admin
    r = c.post("/admin/fields", data={"csrf_token": tok(c), "label": "Favourite Programming Language",
                                      "type": "text", "target": "profile", "show_public": "1"})
    assert r.status_code == 302
    assert "Favourite Programming Language" in c.get("/admin/profile").get_data(as_text=True)
    c.post("/admin/profile", data={"csrf_token": tok(c), "f_full_name": "Jane", "vis_full_name": "1",
                                   "f_cf_favourite_programming_language": "Python",
                                   "vis_cf_favourite_programming_language": "1", "action": "publish"})
    html = c.get("/").get_data(as_text=True)
    assert "Favourite Programming Language" in html and "Python" in html
    # dropdown on education + multi select + list
    c.post("/admin/fields", data={"csrf_token": tok(c), "label": "Mode", "type": "select", "target": "education",
                                  "options": "Online\nOn campus", "show_public": "1"})
    c.post("/admin/fields", data={"csrf_token": tok(c), "label": "Clubs", "type": "multiselect", "target": "education",
                                  "options": "Chess\nRobotics", "show_public": "1"})
    c.post("/admin/fields", data={"csrf_token": tok(c), "label": "Notes list", "type": "list", "target": "education", "show_public": "1"})
    c.post("/admin/s/education/new", data={"csrf_token": tok(c), "f_institution": "CF Uni", "visible": "1", "action": "publish",
                                           "f_cf_mode": "On campus", "f_cf_clubs": ["Chess", "Robotics"],
                                           "f_cf_notes_list[]": ["one", "two"]})
    lst = c.get("/admin/s/education").get_data(as_text=True)
    iid = int(re.findall(r"/admin/i/(\d+)/edit", lst)[-1])
    uid = re.search(r"/s/education/([0-9a-f]{32})", c.get("/").get_data(as_text=True)).group(1)
    html = c.get("/").get_data(as_text=True)
    page = None
    for u in re.findall(r"/s/education/([0-9a-f]{32})", html):
        h = c.get(f"/s/education/{u}").get_data(as_text=True)
        if "CF Uni" in h:
            page = h
    assert page and "On campus" in page and "Robotics" in page and "<li>two</li>" in page


def test_custom_section(admin):
    c = admin
    c.post("/admin/sections/new", data={"csrf_token": tok(c), "title": "Publications", "layout": "cards"})
    assert "Publications" in c.get("/admin/sections").get_data(as_text=True)
    c.post("/admin/s/publications/new", data={"csrf_token": tok(c), "f_title": "My Paper", "visible": "1", "action": "publish",
                                             "f_description": "<p>Great <script>alert(1)</script>work</p>"})
    html = c.get("/").get_data(as_text=True)
    assert "My Paper" in html and "<script>alert" not in html
    d = c.get("/admin/s/publications").get_data(as_text=True)
    assert c.post("/admin/sections/publications/delete", data={"csrf_token": tok(c), "confirm": "yes"}).status_code == 302
    assert "My Paper" not in c.get("/").get_data(as_text=True)


def test_section_hide_and_reorder(admin):
    c = admin
    c.post("/admin/sections/skills/move/up", data={"csrf_token": tok(c)})
    html = c.get("/").get_data(as_text=True)
    assert html.index('id="skills"') < html.index('id="experience"')
    form = {"csrf_token": tok(c)}
    for k in ["about", "education", "experience", "skills", "projects", "certifications", "learning", "achievements", "resumes", "contact"]:
        form["title_" + k] = k.title()
        if k != "projects":
            form["visible_" + k] = "1"
    c.post("/admin/sections", data=form)
    assert 'id="projects"' not in c.get("/").get_data(as_text=True)


def test_file_upload_and_resume(admin):
    c = admin
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    r = c.post("/admin/s/resumes/new", data={"csrf_token": tok(c), "f_label": "v1", "visible": "1", "action": "publish",
                                             "up_file": (io.BytesIO(pdf), "cv.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 302
    html = c.get("/").get_data(as_text=True)
    m = re.search(r'href="(/media/[0-9a-f]{32}\.pdf)\?dl=1"', html)
    assert m
    r = c.get(m.group(1) + "?dl=1")
    assert r.status_code == 200 and r.data.startswith(b"%PDF") and "attachment" in r.headers["Content-Disposition"]
    # bad extension rejected
    r = c.post("/admin/s/resumes/new", data={"csrf_token": tok(c), "f_label": "bad", "action": "publish",
                                             "up_file": (io.BytesIO(b"x"), "evil.exe")}, content_type="multipart/form-data")
    assert r.status_code == 200 and "not allowed" in r.get_data(as_text=True)
    # default resume switch
    c.post("/admin/s/resumes/new", data={"csrf_token": tok(c), "f_label": "v2", "visible": "1", "action": "publish",
                                         "up_file": (io.BytesIO(pdf + b"2"), "cv2.pdf")}, content_type="multipart/form-data")
    lst = c.get("/admin/s/resumes").get_data(as_text=True)
    ids = re.findall(r"/admin/i/(\d+)/do/default", lst)
    assert ids
    c.post(f"/admin/i/{ids[0]}/do/default", data={"csrf_token": tok(c)})
    assert c.get("/resume").status_code == 302


def test_media_traversal(admin):
    assert admin.get("/media/../app.py").status_code in (404, 400)
    assert admin.get("/media/..%2Fapp.py").status_code == 404


def test_export_import_backup_restore(admin):
    c = admin
    exp = c.get("/admin/data/export/personal.json")
    payload = json.loads(exp.data)
    assert payload["format"] == "portfolio-cms/1" and payload["items"]
    site = json.loads(c.get("/admin/data/export/website.json").data)
    assert site["kind"] == "website"
    # delete everything in education then import to restore
    lst = c.get("/admin/s/education").get_data(as_text=True)
    for iid in re.findall(r"/admin/i/(\d+)/edit", lst):
        c.post(f"/admin/i/{iid}/delete", data={"csrf_token": tok(c), "confirm": "yes"})
    assert "Sample University" not in c.get("/").get_data(as_text=True)
    r = c.post("/admin/data/import", data={"csrf_token": tok(c), "mode": "merge",
                                           "file": (io.BytesIO(exp.data), "x.json")}, content_type="multipart/form-data")
    assert r.status_code == 302
    assert "Sample University" in c.get("/").get_data(as_text=True)
    # bad import
    r = c.post("/admin/data/import", data={"csrf_token": tok(c), "mode": "merge",
                                           "file": (io.BytesIO(b'{"a":1}'), "x.json")}, content_type="multipart/form-data", follow_redirects=True)
    assert "Import failed" in r.get_data(as_text=True)
    # backup & restore
    bk = c.get("/admin/data/backup.zip")
    assert bk.status_code == 200 and "portfolio.db" in zipfile.ZipFile(io.BytesIO(bk.data)).namelist()
    lst = c.get("/admin/s/projects").get_data(as_text=True)
    for iid in re.findall(r"/admin/i/(\d+)/edit", lst):
        c.post(f"/admin/i/{iid}/delete", data={"csrf_token": tok(c), "confirm": "yes"})
    assert "Sample ML Project" not in c.get("/").get_data(as_text=True)
    r = c.post("/admin/data/restore", data={"csrf_token": tok(c), "confirm": "yes",
                                            "file": (io.BytesIO(bk.data), "b.zip")}, content_type="multipart/form-data", follow_redirects=True)
    assert "Backup restored" in r.get_data(as_text=True)
    assert "Sample ML Project" in c.get("/").get_data(as_text=True)
    r = c.post("/admin/data/restore", data={"csrf_token": tok(c), "confirm": "yes",
                                            "file": (io.BytesIO(b"nope"), "b.zip")}, content_type="multipart/form-data", follow_redirects=True)
    assert "Restore failed" in r.get_data(as_text=True)


def test_skills_categories_and_no_percentage(admin):
    c = admin
    html = c.get("/").get_data(as_text=True)
    assert "Programming Languages" in html and "Advanced" in html and "%" not in re.sub(r"style=\"[^\"]*\"", "", html.split('id="skills"')[1].split("</section>")[0])
    c.post("/admin/s/skill_categories/new", data={"csrf_token": tok(c), "f_name": "Databases", "visible": "1", "action": "publish"})
    form = c.get("/admin/s/skills/new").get_data(as_text=True)
    assert "Databases" in form


def test_unsafe_urls_neutralised(admin):
    c = admin
    r = c.post("/admin/s/projects/new", data={"csrf_token": tok(c), "f_name": "XSS", "visible": "1", "action": "publish",
                                              "f_github_url": "javascript:alert(1)"})
    assert r.status_code == 200 and "not a valid web address" in r.get_data(as_text=True)
