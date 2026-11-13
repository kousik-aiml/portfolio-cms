# Personal Portfolio + Admin Dashboard

A Flask + SQLite website where **all content is managed in the browser**. No code, templates or database
files need editing for normal updates.

## Run

```bash
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000   (admin: /admin)
```

On first visit to `/admin` you create your own password (nothing is pre-set). Do this before exposing the
site publicly. Sample content ("Alex Sample") is provided; edit or delete all of it from the admin.

Production: `pip install gunicorn && gunicorn -w 2 'app:create_app()'` behind HTTPS.
Env vars: `PORTFOLIO_DATA_DIR` (where the DB + uploads live, default `./data`), `PORT`, `HOST`,
`PORTFOLIO_MAX_UPLOAD_MB`.

## What you can manage (Admin)
- **Profile** – all 23 requested fields (+ your own), each with a *Show on website* tick; draft / publish.
- **Education, Experience, Skills (unlimited categories, labels not percentages), Certifications,
  Projects, Learning journey, Achievements, Resume versions** – unlimited records; each can be
  drafted, published, hidden, reordered (drag or ▲▼), duplicated, previewed, deleted (with confirmation),
  and carries file attachments + external links.
- **Sections & order** – rename, hide, reorder, choose layout, and create your own sections.
- **Custom fields** – 15 types (short/long text, number, date, email, phone, URL, image, file, video URL,
  dropdown, multi-select, checkbox, rich text, repeatable list) attachable to the profile, any built-in
  section, or your own sections.
- **Resume** – upload several PDFs, set the default, preview, download, replace.
- **Preview** – see drafts and unpublished edits exactly as visitors will before publishing.
- **Data** – export personal info (JSON), export website content (JSON), import (merge/replace),
  full backup (.zip with DB + uploads), restore.

Visitors only ever see the last *published* version of anything.

## Tests
`python -m pytest tests`

## Notes
- Back up before restoring/replacing; restore keeps the old DB as `data/portfolio.db.before-restore`.
- JSON exports reference uploaded files by name; use the .zip backup to move files.
- Rich text is sanitised; uploads are extension-checked; all forms are CSRF-protected.
