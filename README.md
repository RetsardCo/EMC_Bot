# EM Bot — Nickname Fix + Persistent Knowledge

## Nickname fix
The introduction cog now:
- pre-checks Manage Nicknames and role hierarchy,
- changes the nickname,
- verifies Discord actually applied the nickname,
- assigns Student/BISCAST/year roles,
- assigns Introduced and removes Unintroduced,
- refuses a second `/setup` after Introduced is present.

Student nickname remains:
`Full Name DAT 4th Year`
or
`Full Name GD 4th Year`

Faculty nickname:
`Full Name Faculty`

## Knowledge
Staff commands:
- `/knowledge_add` — upload PDF or CSV
- `/knowledge_list` — list stored source documents

Knowledge files are persisted under:
`knowledge/source/` — original uploaded PDFs/CSVs
`knowledge/cache/` — generated extracted knowledge
`knowledge/manifest.json` — hashes and metadata

On every normal bot restart:
- existing matching cache is reused,
- missing cache is regenerated,
- changed source files are reprocessed.

No database is required.

If the VM itself is destroyed/recreated and its disk is lost, local files are lost too.
For that case, the private Discord knowledge channel should remain the master backup.

## PDF fallback
Gemini is tried first.
OpenRouter is the fallback for PDF processing.

## CSV
CSV is parsed locally, so no AI request is needed for basic row/column extraction.

## Important
Add `cogs.knowledge` to bot.py before restarting, otherwise `/knowledge_add`
and `/knowledge_list` will not appear.


## Knowledge import/export
- `/knowledge_export` sends a complete ZIP backup containing `source/`, `cache/`, and `manifest.json`.
- `/knowledge_export_md` sends the generated Markdown cache files.
- `/knowledge_import` restores a complete ZIP backup.
Only Moderator and EMC Faculty can use these commands.


## Knowledge GUI
Use `/knowledge` as Moderator or EMC Faculty to open a private Discord panel.
It lists stored source documents and provides a dropdown for deletion with a
separate confirmation button.

Deleting from the GUI removes:
- `knowledge/source/<document>`
- `knowledge/cache/<generated cache>`
- the document entry from `manifest.json`

Existing `/knowledge_add`, `/knowledge_list`, `/knowledge_export`,
`/knowledge_export_md`, and `/knowledge_import` remain available.


## Strict official-document mode

The AI system now includes the OFFICIAL DOCUMENT RULE requested by the administrator.
Uploaded official documents are authoritative for information they cover.
The AI must not invent missing curriculum information and must say verified
information is unavailable when the documents do not support an answer.

Use `/knowledge_rebuild` to reprocess existing PDFs/CSVs with the strict extraction
rules. This is important because an older cached `.md` file may already contain
an incorrect extraction.

For the curriculum document that produced incorrect answers, delete the old
source/cache through `/knowledge`, re-upload the original PDF, and then run
`/knowledge_rebuild` before testing `/ask` again.


## Verified-document workflow

`/knowledge_add` now behaves differently by file type:

- JSON: verified immediately; no AI conversion.
- CSV: verified immediately; parsed locally; no AI conversion.
- PDF: extracted as a **draft** using Gemini/OpenRouter and never exposed to
  `/ask` until a Moderator or EMC Faculty reviews and approves it.

`/knowledge` opens the staff GUI. If drafts are present, it opens a second
private review panel where staff can select a draft, read a preview, and choose
`Approve` or `Reject & Delete`.

Approved PDF knowledge is moved into the normal verified cache and becomes
available to `/ask`.

Rejected PDFs are removed from the local knowledge source/draft cache.

This makes an AI PDF extraction a convenience/draft rather than an authoritative
source. For maximum accuracy, upload human-reviewed JSON/CSV for curriculum data.


## Direct JSON curriculum lookup

Verified JSON curriculum documents are now read directly for curriculum
questions. The AI does not need to search the generated Markdown cache for
these requests.

For a question such as:
`/ask can you give me the list of the subjects in 3rd year game dev?`

the router:
1. Detects curriculum intent.
2. Finds the verified JSON with the matching major.
3. Selects the exact requested year and semester sections.
4. Passes those exact records to the final AI for formatting.
5. Does not use conflicting PDF-derived knowledge when the direct JSON match exists.

Staff can test this without calling the AI using:
`/knowledge_test question:<curriculum question>`


## Curriculum formatting improvement

For curriculum lists, the AI now uses unnumbered semester headings and restarts
subject numbering under each semester:

**First Semester**
1. ...
2. ...

**Second Semester**
1. ...
2. ...

The underlying course data is unchanged.


## Current / Archived Curriculum Manager

For curriculum JSON documents, `/knowledge` now includes a Curriculum Manager.

Each curriculum has a lifecycle:
- ✅ CURRENT — used by direct curriculum lookup and `/ask`
- 🔒 VERIFIED — reviewed and available as structured knowledge, but not active
- 🗃️ ARCHIVED — retained for history but ignored by current curriculum lookup

When a new JSON curriculum is uploaded:
- If there is no current curriculum for that major, it becomes CURRENT automatically.
- If a current curriculum already exists, the new file becomes VERIFIED.
- Staff can open `/knowledge` → Curriculum Manager → Set as Current.

When a curriculum is set as Current, other curricula for the same major are
automatically archived.

This means an update such as:
`2023_bsemc-gd_curr_approved.json`
→ `2026_bsemc-gd_curr_approved.json`

can keep both files while EM Bot uses only the selected CURRENT curriculum.


## General Knowledge Manager

The manager is now document-category based, not curriculum-only.

Supported categories:
- curriculum
- admissions
- student_handbook
- rules
- faq
- events
- policies
- faculty
- scholarship
- internship
- specialization
- academic_calendar
- syllabus
- other

Document lifecycle:
- 🟡 DRAFT — AI-extracted PDF awaiting staff review
- 🔒 VERIFIED — approved/structured knowledge
- ✅ CURRENT — active document for its category/scope
- 🗃️ ARCHIVED — retained but not active

Single-current categories include curriculum, admissions, student handbook, rules,
policies, and academic calendar. Other categories can have multiple current
documents at once.

For a new JSON curriculum, the existing curriculum-specific direct lookup still
works with the CURRENT curriculum for that major. The general manager now also
handles all other official documents.


## Direct structured lookup for all official JSON

Verified JSON is now checked before the generic Markdown/PDF fallback for
handbooks, attendance, admissions, grading, scholarships, internships, rules,
FAQs, events, policies, and other official structured documents.

Use `/knowledge_test_json question:<...>` to verify direct JSON retrieval without
calling the AI.


## Unified `/knowledge_test`

The two previous diagnostics are merged into one command.

`/knowledge_test` reports:
- Expected source
- Category
- Status used
- Route
- Expected fields
- Compact expected answer data

Use this command for curriculum, handbooks, policies, program specifications,
course descriptions, admissions, scholarships, and other structured knowledge.


## Exact course-code retrieval

`/knowledge_test` now treats an explicit course code such as `GD 302` as an
exact lookup. It searches verified JSON `courses[].code` records and returns
the matching course record. An unrelated PDF/Markdown fallback cannot replace
an exact JSON course-code match.

Example:
`/knowledge_test question: What is GD 302?`
should select `BSEMC_course_descriptions.json` and show the GD 302 record.


## Knowledge Manager bulk activation

The `/knowledge` GUI now includes:
- `✅ Set All Verified as Current` — activates all eligible verified JSON/CSV
  documents. It does NOT activate PDF/Markdown drafts.
- `🔧 Repair JSON/CSV Status` — fixes legacy manifests where JSON/CSV was
  incorrectly labeled DRAFT.
- Existing document selector/status controls remain available.

Single-current categories are protected: if multiple verified documents conflict
in the same category/scope, they are skipped instead of silently choosing one.

### Pending Document Review

The pending review section is specifically for AI-extracted PDF documents.
The bot converts the PDF extraction into Markdown under `knowledge/drafts/`.
Those Markdown drafts are not authoritative and are not used by `/ask` until a
staff member approves them.
