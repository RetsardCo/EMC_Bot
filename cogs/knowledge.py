from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
import urllib.request
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .common import is_staff

KNOWLEDGE_DIR = Path(os.getenv("KNOWLEDGE_DIR", "knowledge"))
SOURCE_DIR = KNOWLEDGE_DIR / "source"
CACHE_DIR = KNOWLEDGE_DIR / "cache"
DRAFT_DIR = KNOWLEDGE_DIR / "drafts"
MANIFEST_PATH = KNOWLEDGE_DIR / "manifest.json"

KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
SOURCE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DRAFT_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_BYTES = int(os.getenv("KNOWLEDGE_MAX_FILE_BYTES", str(8 * 1024 * 1024)))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_KNOWLEDGE_MODEL = os.getenv(
    "OPENROUTER_KNOWLEDGE_MODEL",
    "google/gemma-4-31b-it:free",
).strip()

EXTRACTION_PROMPT = """
You are the official-document extraction engine for EM Bot.

The supplied PDF or CSV is an authoritative source document.

STRICT RULES:
1. Extract only information visibly or explicitly present in the document.
2. Never infer, guess, autocomplete, or replace course codes, subject titles,
   week numbers, module names, units, prerequisites, dates, requirements, or policies.
3. Preserve the document's exact terminology and labels.
4. Preserve table row and column relationships. Never merge rows from different
   weeks, semesters, modules, subjects, or sections.
5. For scanned/image-based PDFs, inspect the page visually and transcribe table
   values exactly as shown.
6. Preserve page numbers and section headings whenever available.
7. If a value cannot be read confidently, write [UNREADABLE] instead of guessing.
8. Never combine information from unrelated documents.
9. Return source-faithful structured knowledge for later retrieval.
""".strip()

def slugify(filename: str) -> str:
    stem = Path(filename).stem.casefold()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "document"

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

def csv_to_markdown(data: bytes) -> str:
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    def cell(v: str) -> str:
        return v.replace("|", "\\|").replace("\n", " ").strip()
    lines = [
        "| " + " | ".join(cell(x) for x in rows[0]) + " |",
        "| " + " | ".join("---" for _ in rows[0]) + " |",
    ]
    lines.extend(
        "| " + " | ".join(cell(x) for x in row) + " |"
        for row in rows[1:]
    )
    return "\n".join(lines)

def json_to_text(data: bytes) -> str:
    obj = json.loads(
        data.decode("utf-8-sig", errors="strict")
    )
    return json.dumps(
        obj,
        indent=2,
        ensure_ascii=False,
    )


def gemini_pdf_sync(data: bytes, filename: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": EXTRACTION_PROMPT}]},
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {
                    "mime_type": "application/pdf",
                    "data": base64.b64encode(data).decode("ascii"),
                }},
                {"text": f"Extract official knowledge from `{filename}` and preserve its tables."},
            ],
        }],
        "generationConfig": {"maxOutputTokens": 6000, "temperature": 0.1},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode())
    parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise RuntimeError("Gemini returned no extracted content.")
    return text

def openrouter_pdf_sync(data: bytes, filename: str) -> str:
    data_url = "data:application/pdf;base64," + base64.b64encode(data).decode("ascii")
    payload = {
        "model": OPENROUTER_KNOWLEDGE_MODEL,
        "messages": [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": f"Extract official knowledge from `{filename}` and preserve its tables."},
                {"type": "file", "file": {"filename": filename, "file_data": data_url}},
            ]},
        ],
        "max_tokens": 6000,
        "temperature": 0.1,
        "plugins": [{"id": "file-parser", "pdf": {"engine": "cloudflare-ai"}}],
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENROUTER_API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode())
    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    text = content if isinstance(content, str) else str(content)
    if not text.strip():
        raise RuntimeError("OpenRouter returned no extracted content.")
    return text.strip()

def cache_path_for(source_name: str, *, draft: bool = False) -> Path:
    directory = DRAFT_DIR if draft else CACHE_DIR
    return directory / f"{slugify(source_name)}.md"

async def process_source_file(
    source_path: Path,
    manifest: dict,
    *,
    force: bool = False,
    verified: bool = False,
) -> str:
    data = source_path.read_bytes()

    if len(data) > MAX_FILE_BYTES:
        raise ValueError(
            f"{source_path.name} exceeds the knowledge file size limit."
        )

    digest = sha256(data)
    entry = manifest.get(source_path.name, {})

    status = "verified" if verified else "draft"
    cache_path = cache_path_for(
        source_path.name,
        draft=not verified,
    )

    if (
        not force
        and entry.get("sha256") == digest
        and entry.get("status") == status
        and cache_path.exists()
    ):
        return "cached"

    lower = source_path.name.casefold()

    if lower.endswith(".csv"):
        extracted = csv_to_markdown(data)
        provider = "local-csv"

    elif lower.endswith(".json"):
        extracted = json_to_text(data)
        provider = "local-json"

    elif lower.endswith(".pdf"):
        extracted = None
        provider = ""

        if GEMINI_API_KEY:
            try:
                extracted = await asyncio.to_thread(
                    gemini_pdf_sync,
                    data,
                    source_path.name,
                )
                provider = "Gemini"
            except Exception as error:
                print(
                    f"Knowledge Gemini failure for "
                    f"{source_path.name}: {error}"
                )

        if extracted is None and OPENROUTER_API_KEY:
            try:
                extracted = await asyncio.to_thread(
                    openrouter_pdf_sync,
                    data,
                    source_path.name,
                )
                provider = "OpenRouter"
            except Exception as error:
                print(
                    f"Knowledge OpenRouter failure for "
                    f"{source_path.name}: {error}"
                )

        if extracted is None:
            raise RuntimeError(
                "No document-AI provider could process the PDF."
            )

    else:
        raise ValueError(
            "Supported files are PDF, CSV, and JSON."
        )

    cache_path.write_text(
        f"# SOURCE_DOCUMENT: {source_path.name}\n"
        f"# SOURCE_SHA256: {digest}\n"
        f"# EXTRACTION_PROVIDER: {provider}\n"
        f"# STATUS: {status.upper()}\n"
        "# AUTHORITY: OFFICIAL_DOCUMENT\n\n"
        f"{extracted.strip()}\n",
        encoding="utf-8",
    )

    manifest[source_path.name] = {
        "sha256": digest,
        "cache": cache_path.name,
        "provider": provider,
        "status": status,
        "source_type": lower.rsplit(".", 1)[-1],
    }
    save_manifest(manifest)

    return "processed"


async def rebuild_missing_or_changed() -> None:
    manifest = load_manifest()

    for source in sorted(SOURCE_DIR.iterdir()):
        if not source.is_file():
            continue

        if source.suffix.casefold() not in {".pdf", ".csv", ".json"}:
            continue

        entry = manifest.get(source.name, {})

        # PDFs are unsafe to trust automatically. If there is no explicit
        # verified status, keep them as drafts.
        is_verified = entry.get("status") == "verified"

        try:
            result = await process_source_file(
                source,
                manifest,
                force=False,
                verified=is_verified,
            )

            if result == "processed":
                print(
                    f"Knowledge {'loaded' if is_verified else 'drafted'}: "
                    f"{source.name}"
                )

        except Exception as error:
            print(
                f"Knowledge startup processing failed for "
                f"{source.name}: {error}"
            )


def _load_verified_json_documents() -> list[tuple[str, dict]]:
    """
    Load CURRENT verified JSON curriculum documents directly from source/.
    Older verified/archived JSON files are deliberately excluded from current
    curriculum retrieval.
    """
    manifest = load_manifest()
    documents: list[tuple[str, dict]] = []

    for path in SOURCE_DIR.glob("*.json"):
        entry = manifest.get(path.name, {})

        if entry.get("status") != "current":
            continue

        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            continue

        if isinstance(data, dict):
            documents.append(
                (path.name, data)
            )

    return documents



def _flatten_json_strings(value, path=""):
    out = []
    if isinstance(value, dict):
        for key, child in value.items():
            p = f"{path}.{key}" if path else str(key)
            out.extend(_flatten_json_strings(child, p))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            out.extend(_flatten_json_strings(child, f"{path}[{i}]"))
    elif value is not None:
        out.append((path, str(value)))
    return out


def _json_category(filename, data):
    manifest = load_manifest()
    category = str(
        manifest.get(filename, {}).get("category", "")
    ).casefold()

    if category and category != "other":
        return category

    # Structure-aware categorization for JSON files that may have generic names.
    if isinstance(data, dict):
        if isinstance(data.get("courses"), list):
            return "course_descriptions"

        if (
            "program_specifications" in data
            or "curriculum_summary" in data
            or "specializations" in data
        ):
            return "program_specifications"

        if "handbook_metadata" in data and "parts" in data:
            return "student_handbook"

        if "curriculum" in data and (
            "program" in data or "major" in data
        ):
            return "curriculum"

    return infer_document_category(
        filename,
        data,
    )


def _json_scope(data):
    for key in ("major", "program", "title", "document", "name"):
        if data.get(key):
            return str(data[key])
    meta = data.get("handbook_metadata")
    if isinstance(meta, dict) and meta.get("title"):
        return str(meta["title"])
    return ""


def _json_allowed_status(filename, category):
    entry = load_manifest().get(filename, {})
    status = str(entry.get("status", "")).casefold()
    if category in SINGLE_CURRENT_CATEGORIES:
        return status == "current"
    return status in {"current", "verified"}


def retrieve_verified_json_knowledge(
    question,
    max_documents=3,
    max_chars=12000,
):
    q = question.casefold()
    tokens = set(
        re.findall(
            r"[a-zA-Z0-9']+",
            q,
        )
    )

    # Exact course-code intent, e.g. "GD 302", "GD302", "CC103".
    code_matches = re.findall(
        r"\b([a-z]{2,5})\s*[- ]?\s*(\d{3,4})\b",
        q,
        flags=re.IGNORECASE,
    )
    requested_codes = {
        f"{prefix.upper()}{digits}"
        for prefix, digits in code_matches
    }

    topic_words = {
        "attendance": (
            "attendance",
            "absence",
            "absences",
            "absent",
            "dropped",
            "drop",
            "class hours",
        ),
        "admissions": (
            "admission",
            "admissions",
            "entrance",
            "applicant",
            "application",
        ),
        "scholarship": (
            "scholarship",
            "scholarships",
            "grant",
        ),
        "grading": (
            "grade",
            "grading",
            "gwa",
            "passing",
            "failed",
            "incomplete",
        ),
        "handbook": (
            "handbook",
            "student handbook",
        ),
        "internship": (
            "internship",
            "ojt",
            "practicum",
        ),
        "rules": (
            "rules",
            "rule",
            "regulation",
            "policy",
            "policies",
        ),
        "curriculum": (
            "curriculum",
            "semester",
            "year",
            "prerequisite",
            "units",
        ),
        "program_specifications": (
            "specialization",
            "specializations",
            "objective",
            "objectives",
            "career",
            "careers",
            "total units",
        ),
        "course_descriptions": (
            "course",
            "courses",
            "course code",
            "course description",
            "credits",
            "prerequisite",
        ),
    }

    active_topics = {
        topic
        for topic, words in topic_words.items()
        if any(
            word in q
            for word in words
        )
    }

    manifest = load_manifest()
    scored = []

    for path in SOURCE_DIR.glob("*.json"):
        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(data, dict):
            continue

        category = _json_category(
            path.name,
            data,
        )

        entry = manifest.get(
            path.name,
            {},
        )
        status = str(
            entry.get(
                "status",
                "",
            )
        ).casefold()

        # Never use archived structured documents.
        if status == "archived":
            continue

        # Determine if this source is eligible. For single-current categories,
        # current is preferred, but a verified source is usable when no current
        # document of that category exists.
        if category in SINGLE_CURRENT_CATEGORIES:
            has_current = any(
                other_name != path.name
                and _json_category(
                    other_name,
                    {},
                ) == category
                and str(
                    other.get(
                        "status",
                        "",
                    )
                ).casefold() == "current"
                for other_name, other in manifest.items()
            )
            if has_current and status != "current":
                continue
            if status not in {"current", "verified"}:
                continue
        else:
            if status not in {"current", "verified"}:
                continue

        text_blob = json.dumps(
            data,
            ensure_ascii=False,
        ).casefold()

        # Exact code matching gets a very large score and only considers
        # documents that actually contain the requested code.
        code_hits = []
        if requested_codes:
            if isinstance(data.get("courses"), list):
                for course in data["courses"]:
                    if not isinstance(course, dict):
                        continue
                    raw_code = str(
                        course.get(
                            "code",
                            "",
                        )
                    ).upper()
                    normalized = re.sub(
                        r"[^A-Z0-9]",
                        "",
                        raw_code,
                    )
                    if normalized in requested_codes:
                        code_hits.append(
                            course
                        )

            # Also support curriculum JSON course entries.
            if not code_hits and isinstance(data.get("curriculum"), list):
                def walk(value):
                    if isinstance(value, dict):
                        raw = str(value.get("code", "")).upper()
                        normalized = re.sub(r"[^A-Z0-9]", "", raw)
                        if normalized in requested_codes:
                            code_hits.append(value)
                        for child in value.values():
                            walk(child)
                    elif isinstance(value, list):
                        for child in value:
                            walk(child)

                walk(data["curriculum"])

            # If a code was explicitly asked for, an exact document match is
            # authoritative; do not let generic word overlap select another file.
            if not code_hits:
                continue

        score = 0

        if requested_codes:
            score += 5000

        if category in active_topics:
            score += 250

        # Prefer source structures that actually match the intent.
        if "specialization" in q or "specializations" in q:
            if isinstance(data.get("program_specifications"), dict):
                score += 1000
            if isinstance(data.get("specializations"), list):
                score += 1000
            if "specializations" in text_blob:
                score += 400

        if "total unit" in q or "how many units" in q:
            if "curriculum_summary" in data:
                score += 1000
            if "total_units" in text_blob:
                score += 500

        if any(
            word in q
            for word in (
                "attendance",
                "absence",
                "absences",
                "dropped",
            )
        ):
            if category == "student_handbook":
                score += 1200

        score += len(
            tokens
            & set(
                re.findall(
                    r"[a-zA-Z0-9']+",
                    text_blob,
                )
            )
        )

        current_bonus = (
            100
            if status == "current"
            else 50
        )
        score += current_bonus

        scope = _json_scope(
            data
        )

        # Relevant leaf fields.
        leaf_scores = []
        for field, value in _flatten_json_strings(data):
            low = value.casefold()
            leaf_tokens = set(
                re.findall(
                    r"[a-zA-Z0-9']+",
                    low,
                )
            )

            leaf_score = len(
                tokens
                & leaf_tokens
            )

            if requested_codes:
                raw_code = re.sub(
                    r"[^A-Z0-9]",
                    "",
                    low,
                )
                if any(
                    re.sub(
                        r"[^A-Z0-9]",
                        "",
                        code.casefold(),
                    ) in raw_code
                    for code in requested_codes
                ):
                    leaf_score += 1000

            if (
                "attendance" in q
                and (
                    "attendance" in low
                    or "absence" in low
                    or "dropped" in low
                )
            ):
                leaf_score += 25

            if (
                "drop" in q
                and (
                    "drop" in low
                    or "dropped" in low
                )
            ):
                leaf_score += 25

            if leaf_score:
                leaf_scores.append(
                    (
                        leaf_score,
                        field,
                        value,
                    )
                )

        leaf_scores.sort(
            reverse=True
        )

        snippets = [
            {
                "field": field,
                "value": value,
            }
            for _, field, value
            in leaf_scores[:20]
        ]

        # For exact code queries, include the entire matching course record.
        exact_records = []
        if code_hits:
            exact_records = code_hits[:5]

        payload = {
            "source_document": path.name,
            "category": category,
            "status": status,
            "scope": scope,
            "authoritative": True,
            "matched_course_records": exact_records,
            "matched_fields": snippets,
        }

        scored.append(
            (
                score,
                current_bonus,
                path.name,
                category,
                payload,
            )
        )

    scored.sort(
        key=lambda item: (
            item[0],
            item[1],
        ),
        reverse=True,
    )

    results = []

    for _, _, filename, category, payload in scored[:max_documents]:
        results.append(
            "DIRECT VERIFIED JSON KNOWLEDGE\n"
            f"SOURCE: {filename}\n"
            f"CATEGORY: {category}\n"
            f"STATUS: {payload['status']}\n"
            "AUTHORITY: VERIFIED_JSON\n"
            "INSTRUCTION: Use exact values from this source. "
            "Do not substitute PDF caches or model memory.\n\n"
            + json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            )[:max_chars]
        )

    return results


def retrieve_structured_curriculum(
    question: str,
) -> list[str]:
    """
    Directly retrieve curriculum sections from verified JSON.

    This does not use semantic ranking or an AI-generated PDF cache.
    It matches the requested specialization/year/semester and then serializes
    the exact JSON records for the final model to format.
    """
    q = question.casefold()

    curriculum_intent = any(
        phrase in q
        for phrase in (
            "curriculum",
            "subject",
            "subjects",
            "course",
            "courses",
            "prerequisite",
            "units",
            "semester",
            "year",
        )
    )
    if not curriculum_intent:
        return []

    # Infer the specialization only from explicit user wording.
    if (
        "game development" in q
        or "game dev" in q
        or re.search(r"\bGD\b", question, flags=re.IGNORECASE)
    ):
        requested_major = "GAME DEVELOPMENT"
    elif (
        "digital animation" in q
        or re.search(r"\bDAT\b", question, flags=re.IGNORECASE)
    ):
        requested_major = "DIGITAL ANIMATION"
    else:
        requested_major = ""

    year_map = {
        "1st year": "FIRST YEAR",
        "first year": "FIRST YEAR",
        "1st": "FIRST YEAR",
        "2nd year": "SECOND YEAR",
        "second year": "SECOND YEAR",
        "2nd": "SECOND YEAR",
        "3rd year": "THIRD YEAR",
        "third year": "THIRD YEAR",
        "3rd": "THIRD YEAR",
        "4th year": "FOURTH YEAR",
        "fourth year": "FOURTH YEAR",
        "4th": "FOURTH YEAR",
    }

    requested_year = next(
        (
            value
            for key, value in year_map.items()
            if key in q
        ),
        None,
    )

    requested_semester = None
    if (
        "second semester" in q
        or "2nd semester" in q
        or "semester 2" in q
    ):
        requested_semester = "Second Semester"
    elif (
        "first semester" in q
        or "1st semester" in q
        or "semester 1" in q
    ):
        requested_semester = "First Semester"

    results: list[str] = []

    for filename, document in _load_verified_json_documents():
        major = str(
            document.get("major", "")
        ).casefold()

        if requested_major:
            if requested_major == "GAME DEVELOPMENT" and "game development" not in major:
                continue
            if requested_major == "DIGITAL ANIMATION" and "digital animation" not in major:
                continue

        curriculum = document.get(
            "curriculum",
            [],
        )
        if not isinstance(curriculum, list):
            continue

        for year_block in curriculum:
            if not isinstance(year_block, dict):
                continue

            year_name = str(
                year_block.get("year", "")
            )

            if requested_year and year_name.casefold() != requested_year.casefold():
                continue

            semesters = year_block.get(
                "semesters",
                [],
            )
            if not isinstance(semesters, list):
                continue

            matched_semesters: list[dict] = []

            for semester_block in semesters:
                if not isinstance(semester_block, dict):
                    continue

                semester_name = str(
                    semester_block.get("semester", "")
                )

                if (
                    requested_semester
                    and semester_name.casefold()
                    != requested_semester.casefold()
                ):
                    continue

                matched_semesters.append(
                    semester_block
                )

            if not matched_semesters:
                continue

            payload = {
                "source_document": filename,
                "institution": document.get("institution"),
                "program": document.get("program"),
                "major": document.get("major"),
                "year": year_name,
                "semesters": matched_semesters,
            }

            results.append(
                "DIRECT VERIFIED CURRICULUM DATA\n"
                f"SOURCE: {filename}\n"
                "AUTHORITY: VERIFIED_JSON\n"
                "INSTRUCTION: Treat every code, title, unit, prerequisite, "
                "year, and semester value below as exact. Do not substitute "
                "or infer values from other documents.\n\n"
                + json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                )
            )

    return results




CATEGORY_CHOICES = (
    "curriculum",
    "admissions",
    "student_handbook",
    "rules",
    "faq",
    "events",
    "policies",
    "faculty",
    "scholarship",
    "internship",
    "specialization",
    "academic_calendar",
    "syllabus",
    "other",
)

# Categories where only one document per scope should be current.
SINGLE_CURRENT_CATEGORIES = {
    "curriculum",
    "admissions",
    "student_handbook",
    "rules",
    "policies",
    "academic_calendar",
}

def infer_document_category(
    filename: str,
    data: dict | None = None,
) -> str:
    name = filename.casefold()
    title = ""
    if isinstance(data, dict):
        title = " ".join(
            str(data.get(key, ""))
            for key in ("title", "document", "name", "category")
        ).casefold()

    haystack = f"{name} {title}"

    patterns = (
        ("curriculum", ("curriculum", "curr")),
        ("program_specifications", ("psg", "program specification", "program specifications")),
        ("course_descriptions", ("course descriptions", "course description", "course_description")),
        ("admissions", ("admission", "admissions")),
        ("student_handbook", ("student handbook", "handbook")),
        ("rules", ("rules", "server rules")),
        ("faq", ("faq", "frequently asked")),
        ("events", ("event", "events", "calendar of activities")),
        ("policies", ("policy", "policies")),
        ("faculty", ("faculty",)),
        ("scholarship", ("scholarship", "scholarships")),
        ("internship", ("internship", "ojt")),
        ("specialization", ("specialization", "specialisation")),
        ("academic_calendar", ("academic calendar", "school calendar")),
        ("syllabus", ("syllabus",)),
    )

    for category, keywords in patterns:
        if any(keyword in haystack for keyword in keywords):
            return category

    return "other"


def is_multiple_current_category(category: str) -> bool:
    return category not in SINGLE_CURRENT_CATEGORIES


def set_generic_current(
    filename: str,
    *,
    category: str,
    scope: str = "",
) -> tuple[bool, str]:
    manifest = load_manifest()
    target = manifest.get(filename)

    if not target:
        return False, "The selected document is not registered."

    target["category"] = category
    target["scope"] = scope
    target["status"] = "current"

    if not is_multiple_current_category(category):
        for other_name, other in manifest.items():
            if other_name == filename:
                continue
            if other.get("status") != "current":
                continue
            if other.get("category") != category:
                continue
            if other.get("scope", "") != scope:
                continue

            other["status"] = "archived"
            manifest[other_name] = other

    manifest[filename] = target
    save_manifest(manifest)
    return True, ""


def archive_generic_document(
    filename: str,
) -> tuple[bool, str]:
    manifest = load_manifest()
    entry = manifest.get(filename)

    if not entry:
        return False, "The selected document is not registered."

    entry["status"] = "archived"
    manifest[filename] = entry
    save_manifest(manifest)
    return True, ""


def generic_manager_documents() -> list[Path]:
    manifest = load_manifest()
    results: list[Path] = []

    for path in SOURCE_DIR.iterdir():
        if not path.is_file():
            continue

        entry = manifest.get(path.name, {})
        if not entry:
            continue

        results.append(path)

    return sorted(
        results,
        key=lambda p: p.name.casefold(),
    )


def generic_status_label(
    filename: str,
) -> str:
    status = str(
        document_metadata(filename).get(
            "status",
            "unknown",
        )
    ).casefold()

    return {
        "current": "✅ CURRENT",
        "verified": "🔒 VERIFIED",
        "archived": "🗃️ ARCHIVED",
        "draft": "🟡 DRAFT",
    }.get(
        status,
        "❔ UNKNOWN",
    )


def generic_category_label(
    filename: str,
) -> str:
    return str(
        document_metadata(filename).get(
            "category",
            "other",
        )
    ).replace(
        "_",
        " ",
    ).title()


def document_metadata(filename: str) -> dict:
    manifest = load_manifest()
    return manifest.get(filename, {})


def save_document_status(
    filename: str,
    status: str,
    *,
    major: str | None = None,
    program: str | None = None,
) -> None:
    manifest = load_manifest()
    entry = manifest.setdefault(filename, {})
    entry["status"] = status

    if major is not None:
        entry["major"] = major
    if program is not None:
        entry["program"] = program

    save_manifest(manifest)


def _json_document_info(
    filename: str,
    data: dict,
) -> tuple[str, str]:
    major = str(data.get("major", "")).strip()
    program = str(data.get("program", "")).strip()
    return major, program


def curriculum_json_documents() -> list[Path]:
    manifest = load_manifest()
    results: list[Path] = []

    for path in SOURCE_DIR.glob("*.json"):
        entry = manifest.get(path.name, {})

        if entry.get("source_type") != "json":
            continue

        try:
            data = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(data, dict):
            continue

        if "curriculum" not in data:
            continue

        results.append(path)

    return sorted(
        results,
        key=lambda p: p.name.casefold(),
    )


def ensure_curriculum_status(
    filename: str,
    data: dict,
) -> str:
    """
    New curriculum JSON becomes current only when there is no existing current
    document for the same major. Otherwise it remains verified until staff
    explicitly selects Set as Current.
    """
    manifest = load_manifest()
    entry = manifest.setdefault(filename, {})

    major, program = _json_document_info(
        filename,
        data,
    )

    entry["major"] = major
    entry["program"] = program
    entry["source_type"] = "json"
    entry.setdefault("status", "verified")

    same_major_current = False

    for other_path in curriculum_json_documents():
        if other_path.name == filename:
            continue

        other = manifest.get(
            other_path.name,
            {},
        )

        if other.get("major", "").casefold() != major.casefold():
            continue

        if other.get("status") == "current":
            same_major_current = True
            break

    if entry.get("status") not in {
        "current",
        "archived",
    }:
        entry["status"] = (
            "verified"
            if same_major_current
            else "current"
        )

    manifest[filename] = entry
    save_manifest(manifest)

    return entry["status"]


def set_curriculum_current(
    filename: str,
) -> tuple[bool, str]:
    manifest = load_manifest()

    path = SOURCE_DIR / filename
    if not path.exists() or path.suffix.casefold() != ".json":
        return False, "The selected document is not a JSON curriculum file."

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return False, "The selected JSON could not be read."

    if not isinstance(data, dict) or "curriculum" not in data:
        return False, "The selected JSON is not recognized as a curriculum document."

    major, program = _json_document_info(
        filename,
        data,
    )

    for other_path in curriculum_json_documents():
        if other_path.name == filename:
            continue

        other_entry = manifest.get(
            other_path.name,
            {}
        )

        if (
            other_entry.get("major", "").casefold()
            == major.casefold()
        ):
            if other_entry.get("status") == "current":
                other_entry["status"] = "archived"
                manifest[other_path.name] = other_entry

    entry = manifest.setdefault(
        filename,
        {}
    )
    entry["status"] = "current"
    entry["source_type"] = "json"
    entry["major"] = major
    entry["program"] = program
    manifest[filename] = entry
    save_manifest(manifest)

    return True, ""


def archive_curriculum(
    filename: str,
) -> tuple[bool, str]:
    manifest = load_manifest()
    entry = manifest.get(filename)

    if not entry:
        return False, "The selected document is not registered."

    if entry.get("status") == "archived":
        return True, ""

    entry["status"] = "archived"
    manifest[filename] = entry
    save_manifest(manifest)

    return True, ""


def document_status_label(filename: str) -> str:
    entry = document_metadata(filename)
    status = entry.get("status", "unknown").casefold()

    labels = {
        "current": "✅ CURRENT",
        "verified": "🔒 VERIFIED",
        "archived": "🗃️ ARCHIVED",
        "draft": "🟡 DRAFT",
    }

    return labels.get(
        status,
        "❔ UNKNOWN",
    )


def curriculum_manager_options() -> list[discord.SelectOption]:
    options: list[discord.SelectOption] = []

    for path in curriculum_json_documents():
        entry = document_metadata(path.name)
        major = entry.get(
            "major",
            "Unknown major",
        )

        status = document_status_label(
            path.name
        )

        options.append(
            discord.SelectOption(
                label=path.name[:100],
                value=path.name,
                description=(
                    f"{status} • {major}"
                )[:100],
            )
        )

    return options



class GenericKnowledgeActionView(discord.ui.View):
    def __init__(
        self,
        filename: str,
    ) -> None:
        super().__init__(timeout=180)
        self.filename = filename

    async def _authorized(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        member = interaction.user
        return (
            isinstance(member, discord.Member)
            and is_staff(member)
        )

    @discord.ui.button(
        label="Set as Current",
        style=discord.ButtonStyle.success,
        emoji="✅",
    )
    async def set_current(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._authorized(interaction):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can manage knowledge.",
                ephemeral=True,
            )
            return

        entry = document_metadata(
            self.filename
        )
        category = str(
            entry.get(
                "category",
                "other",
            )
        )
        scope = str(
            entry.get(
                "scope",
                "",
            )
        )

        ok, error = set_generic_current(
            self.filename,
            category=category,
            scope=scope,
        )

        if not ok:
            await interaction.response.edit_message(
                content=f"1. Could not set this document as current.\n\n2. {error}",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"✅ **{self.filename}** is now **CURRENT**.\n\n"
                f"Category: **{generic_category_label(self.filename)}**.\n\n"
                f"Scope: **{scope or 'global'}**.\n\n"
                + (
                    "Other current documents in the same single-current category and scope were archived."
                    if not is_multiple_current_category(category)
                    else "This category allows multiple current documents."
                )
            ),
            view=None,
        )

    @discord.ui.button(
        label="Archive",
        style=discord.ButtonStyle.secondary,
        emoji="🗃️",
    )
    async def archive(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._authorized(interaction):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can manage knowledge.",
                ephemeral=True,
            )
            return

        ok, error = archive_generic_document(
            self.filename
        )

        if not ok:
            await interaction.response.edit_message(
                content=f"1. Could not archive this document.\n\n2. {error}",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"🗃️ **{self.filename}** is now **ARCHIVED**.\n\n"
                "It will remain stored but won't be selected as current."
            ),
            view=None,
        )


class GenericKnowledgeSelect(discord.ui.Select):
    def __init__(self) -> None:
        documents = generic_manager_documents()
        options = []

        for path in documents[:25]:
            entry = document_metadata(path.name)
            category = str(
                entry.get(
                    "category",
                    "other",
                )
            ).replace(
                "_",
                " ",
            ).title()

            status = generic_status_label(
                path.name
            )

            options.append(
                discord.SelectOption(
                    label=path.name[:100],
                    value=path.name,
                    description=(
                        f"{status} • {category}"
                    )[:100],
                )
            )

        if not options:
            options = [
                discord.SelectOption(
                    label="No knowledge documents",
                    value="__none__",
                )
            ]

        super().__init__(
            placeholder="Select a knowledge document...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not documents,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        filename = self.values[0]

        if filename == "__none__":
            await interaction.response.send_message(
                "1. No knowledge documents are available.",
                ephemeral=True,
            )
            return

        entry = document_metadata(
            filename
        )

        category = str(
            entry.get(
                "category",
                "other",
            )
        )

        scope = str(
            entry.get(
                "scope",
                "",
            )
        )

        await interaction.response.send_message(
            (
                f"📚 **Knowledge Document**\n\n"
                f"**File:** `{filename}`\n"
                f"**Category:** **{category.replace('_', ' ').title()}**\n"
                f"**Status:** {generic_status_label(filename)}\n"
                f"**Scope:** `{scope or 'global'}`\n\n"
                "Choose an action:"
            ),
            view=GenericKnowledgeActionView(
                filename
            ),
            ephemeral=True,
        )


class GenericKnowledgeManagerView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

        if generic_manager_documents():
            self.add_item(
                GenericKnowledgeSelect()
            )


class CurriculumActionView(discord.ui.View):
    def __init__(
        self,
        filename: str,
    ) -> None:
        super().__init__(timeout=180)
        self.filename = filename

    async def _staff_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        member = interaction.user

        return (
            isinstance(member, discord.Member)
            and is_staff(member)
        )

    @discord.ui.button(
        label="Set as Current",
        style=discord.ButtonStyle.success,
        emoji="✅",
    )
    async def set_current(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._staff_check(interaction):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can manage curriculum status.",
                ephemeral=True,
            )
            return

        ok, error = set_curriculum_current(
            self.filename
        )

        if not ok:
            await interaction.response.edit_message(
                content=f"1. Could not set this curriculum as current.\n\n2. {error}",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"✅ **{self.filename}** is now the **CURRENT** curriculum.\n\n"
                "Any other curriculum JSON for the same major was automatically archived."
            ),
            view=None,
        )

    @discord.ui.button(
        label="Archive",
        style=discord.ButtonStyle.secondary,
        emoji="🗃️",
    )
    async def archive(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._staff_check(interaction):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can manage curriculum status.",
                ephemeral=True,
            )
            return

        ok, error = archive_curriculum(
            self.filename
        )

        if not ok:
            await interaction.response.edit_message(
                content=f"1. Could not archive this curriculum.\n\n2. {error}",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"🗃️ **{self.filename}** is now **ARCHIVED**.\n\n"
                "It will no longer be selected as the current curriculum."
            ),
            view=None,
        )


class CurriculumManagerSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = curriculum_manager_options()

        if not options:
            options = [
                discord.SelectOption(
                    label="No curriculum JSON documents found",
                    value="__none__",
                )
            ]

        super().__init__(
            placeholder="Select a curriculum...",
            min_values=1,
            max_values=1,
            options=options[:25],
            disabled=not curriculum_json_documents(),
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        filename = self.values[0]

        if filename == "__none__":
            await interaction.response.send_message(
                "1. No curriculum JSON documents are available.",
                ephemeral=True,
            )
            return

        entry = document_metadata(
            filename
        )

        await interaction.response.send_message(
            (
                f"📘 **Curriculum Manager**\n\n"
                f"**File:** `{filename}`\n"
                f"**Major:** {entry.get('major', 'Unknown')}\n"
                f"**Program:** {entry.get('program', 'Unknown')}\n"
                f"**Status:** {document_status_label(filename)}\n\n"
                "Choose an action:"
            ),
            view=CurriculumActionView(
                filename
            ),
            ephemeral=True,
        )


class CurriculumManagerView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

        if curriculum_json_documents():
            self.add_item(
                CurriculumManagerSelect()
            )


def retrieve_knowledge(
    question: str,
    max_files: int = 3,
    max_chars: int = 12000,
) -> list[str]:
    q = question.casefold()
    tokens = set(re.findall(r"[a-zA-Z0-9']+", q))

    is_curriculum_query = any(
        phrase in q
        for phrase in (
            "curriculum",
            "subjects",
            "subject list",
            "courses",
            "course list",
            "units",
            "prerequisite",
            "semester",
            "year",
            "game development",
            "game dev",
            "digital animation",
            "dat",
            "gd",
        )
    )

    year_signals = re.findall(
        r"\b(?:1st|2nd|3rd|4th)\s+year\b",
        q,
    )
    module_signals = re.findall(
        r"\bmodule\s*\d+\b",
        q,
    )
    week_signals = re.findall(
        r"\bweek\s*\d+(?:\s*-\s*\d+)?\b",
        q,
    )

    scored: list[tuple[int, int, Path, str, str]] = []
    manifest = load_manifest()

    for path in CACHE_DIR.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        lower = text.casefold()
        stem = path.stem.casefold()

        # Identify source metadata.
        source_match = re.search(
            r"# SOURCE_DOCUMENT:\s*(.+)",
            text,
            flags=re.IGNORECASE,
        )
        source_name = (
            source_match.group(1).strip()
            if source_match
            else path.name
        )

        entry = manifest.get(source_name, {})
        source_type = str(
            entry.get("source_type", "")
        ).casefold()
        status = str(
            entry.get("status", "")
        ).casefold()
        provider = str(
            entry.get("provider", "")
        ).casefold()

        # Only verified knowledge is retrieved.
        if status and status != "verified":
            continue

        score = 0

        # Generic token overlap.
        score += len(
            tokens
            & set(
                re.findall(
                    r"[a-zA-Z0-9']+",
                    lower,
                )
            )
        )

        # Strong preference for user-supplied structured knowledge.
        if source_type == "json":
            score += 120
        elif source_type == "csv":
            score += 100
        elif source_type == "pdf":
            # PDF-derived knowledge is still accepted if approved, but it
            # should not beat an explicitly verified JSON/CSV curriculum.
            score += 20

        if provider == "local-json":
            score += 40
        if provider == "local-csv":
            score += 30

        if is_curriculum_query:
            if "bsemc" in source_name.casefold():
                score += 30
            if "gd" in source_name.casefold() or "game" in source_name.casefold():
                score += 35
            if "dat" in source_name.casefold() and "game dev" not in q:
                score += 10

        for year in year_signals:
            if year in lower:
                score += 35
            if year.replace(" ", "_") in stem:
                score += 20

        for module in module_signals:
            if module in lower:
                score += 25

        for week in week_signals:
            if week in lower:
                score += 25

        # Direct exact phrase match is very strong.
        if "third year" in q and "third year" in lower:
            score += 45
        if "second year" in q and "second year" in lower:
            score += 45
        if "first year" in q and "first year" in lower:
            score += 45
        if "fourth year" in q and "fourth year" in lower:
            score += 45

        # Fresh verified JSON/CSV should outrank older PDF material when both
        # cover the same topic.
        priority = 3 if source_type == "json" else 2 if source_type == "csv" else 1

        if score > 0:
            scored.append(
                (
                    score,
                    priority,
                    path,
                    text,
                    source_name,
                )
            )

    scored.sort(
        key=lambda item: (
            item[1],
            item[0],
        ),
        reverse=True,
    )

    results: list[str] = []

    for _, _, path, text, source_name in scored[:max_files]:
        results.append(
            f"SOURCE DOCUMENT: {source_name}\n"
            "AUTHORITY: VERIFIED_OFFICIAL_DOCUMENT\n"
            "SOURCE TYPE: "
            f"{manifest.get(source_name, {}).get('source_type', 'unknown')}\n"
            "INSTRUCTION: Use only facts explicitly present in this source. "
            "For structured JSON/CSV, treat the fields and values as exact "
            "authoritative data. Do not substitute facts from another document.\n\n"
            f"{text[:max_chars]}"
        )

    return results


def build_backup_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for root_dir in (SOURCE_DIR, CACHE_DIR, DRAFT_DIR):
            if not root_dir.exists():
                continue
            for path in root_dir.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(KNOWLEDGE_DIR))
        if MANIFEST_PATH.exists():
            archive.write(MANIFEST_PATH, MANIFEST_PATH.relative_to(KNOWLEDGE_DIR))
    return buffer.getvalue()


def validate_backup_zip(data: bytes) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            names = archive.namelist()
            if not names:
                return False, "The ZIP is empty."

            for name in names:
                normalized = name.replace("\\", "/")
                if normalized.endswith("/"):
                    continue
                if normalized.startswith("/") or ".." in Path(normalized).parts:
                    return False, "The backup contains an unsafe path."
                if normalized != "manifest.json" and not (
                    normalized.startswith("source/")
                    or normalized.startswith("cache/")
                ):
                    return False, "The backup contains an unsupported file path."

        return True, ""
    except zipfile.BadZipFile:
        return False, "The uploaded file is not a valid ZIP archive."


def restore_backup_zip(data: bytes) -> int:
    restored = 0
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            archive.extractall(temp_path)

        for relative_dir, target_dir in (("source", SOURCE_DIR), ("cache", CACHE_DIR), ("drafts", DRAFT_DIR)):
            extracted_dir = temp_path / relative_dir
            if not extracted_dir.exists():
                continue

            target_dir.mkdir(parents=True, exist_ok=True)
            for source_file in extracted_dir.rglob("*"):
                if source_file.is_file():
                    relative = source_file.relative_to(extracted_dir)
                    destination = target_dir / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_file, destination)
                    restored += 1

        manifest_source = temp_path / "manifest.json"
        if manifest_source.exists():
            shutil.copy2(manifest_source, MANIFEST_PATH)
            restored += 1

    return restored



def knowledge_documents() -> list[Path]:
    if not SOURCE_DIR.exists():
        return []
    return sorted(
        [p for p in SOURCE_DIR.iterdir() if p.is_file()],
        key=lambda p: p.name.casefold(),
    )


def delete_knowledge_document(filename: str) -> tuple[bool, str]:
    source = SOURCE_DIR / filename
    cache = CACHE_DIR / f"{slugify(filename)}.md"
    try:
        deleted = False
        if source.exists() and source.is_file():
            source.unlink()
            deleted = True
        if cache.exists() and cache.is_file():
            cache.unlink()
            deleted = True
        manifest = load_manifest()
        if filename in manifest:
            del manifest[filename]
            save_manifest(manifest)
            deleted = True
        if not deleted:
            return False, "That document is no longer in the knowledge base."
        return True, ""
    except OSError as error:
        return False, str(error)


class KnowledgeDeleteConfirmView(discord.ui.View):
    def __init__(self, filename: str) -> None:
        super().__init__(timeout=60)
        self.filename = filename

    @discord.ui.button(
        label="Delete",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.edit_message(
                content="1. Only Moderator and EMC Faculty can delete knowledge.",
                view=None,
            )
            return

        ok, error = delete_knowledge_document(self.filename)
        if not ok:
            await interaction.response.edit_message(
                content=f"1. The document could not be deleted.\n\n2. {error}",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"✅ **{self.filename}** was deleted.\n\n"
                "The source file, generated cache, and manifest entry were removed."
            ),
            view=None,
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Deletion cancelled.",
            view=None,
        )


class KnowledgeDeleteSelect(discord.ui.Select):
    def __init__(self) -> None:
        documents = knowledge_documents()
        options = [
            discord.SelectOption(
                label=p.name[:100],
                value=p.name,
                description="Delete this document and its generated cache.",
            )
            for p in documents[:25]
        ]
        if not options:
            options = [
                discord.SelectOption(
                    label="No documents available",
                    value="__none__",
                    description="Upload a PDF or CSV first.",
                )
            ]

        super().__init__(
            placeholder="Select a document to delete...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not documents,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        filename = self.values[0]
        if filename == "__none__":
            await interaction.response.send_message(
                "1. There are no knowledge documents to delete.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"⚠️ Delete **{filename}**?",
            view=KnowledgeDeleteConfirmView(filename),
            ephemeral=True,
        )


class KnowledgePanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)
        if knowledge_documents():
            self.add_item(KnowledgeDeleteSelect())

    @staticmethod
    def panel_text() -> str:
        docs = knowledge_documents()
        if not docs:
            return (
                "📚 **EM Bot Knowledge Manager**\n\n"
                "**No documents are stored yet.**\n\n"
                "Use `/knowledge_add` to upload a PDF or CSV.\n"
                "Use `/knowledge_export` to create a backup.\n"
                "Use `/knowledge_import` to restore a backup."
            )

        lines = "\n".join(
            f"{i}. `{p.name}`"
            for i, p in enumerate(docs[:25], 1)
        )
        extra = (
            f"\n\nShowing 25 of {len(docs)}."
            if len(docs) > 25
            else ""
        )
        return (
            "📚 **EM Bot Knowledge Manager**\n\n"
            f"**Documents: {len(docs)}**\n\n"
            f"{lines}{extra}\n\n"
            "Select a document below to delete it."
        )



def draft_documents() -> list[Path]:
    if not DRAFT_DIR.exists():
        return []
    return sorted(
        [
            p
            for p in DRAFT_DIR.iterdir()
            if p.is_file()
        ],
        key=lambda p: p.name.casefold(),
    )


def promote_draft(filename: str) -> tuple[bool, str]:
    draft = DRAFT_DIR / filename
    if not draft.exists():
        return False, "The draft no longer exists."

    source_name = None
    manifest = load_manifest()

    for name, entry in manifest.items():
        if entry.get("cache") == filename and entry.get("status") == "draft":
            source_name = name
            break

    if source_name is None:
        return False, "No matching draft metadata was found."

    verified_path = CACHE_DIR / filename

    try:
        shutil.copy2(draft, verified_path)

        entry = manifest[source_name]
        entry["status"] = "verified"
        entry["cache"] = verified_path.name
        manifest[source_name] = entry
        save_manifest(manifest)

        draft.unlink()
        return True, ""
    except OSError as error:
        return False, str(error)


def reject_draft(filename: str) -> tuple[bool, str]:
    draft = DRAFT_DIR / filename
    if not draft.exists():
        return False, "The draft no longer exists."

    manifest = load_manifest()
    source_name = None

    for name, entry in manifest.items():
        if entry.get("cache") == filename and entry.get("status") == "draft":
            source_name = name
            break

    try:
        draft.unlink()

        if source_name is not None:
            source_path = SOURCE_DIR / source_name
            if source_path.exists():
                source_path.unlink()

            del manifest[source_name]
            save_manifest(manifest)

        return True, ""
    except OSError as error:
        return False, str(error)


class DraftReviewView(discord.ui.View):
    def __init__(self, draft_filename: str) -> None:
        super().__init__(timeout=180)
        self.draft_filename = draft_filename

    @discord.ui.button(
        label="Approve",
        style=discord.ButtonStyle.success,
        emoji="✅",
    )
    async def approve(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        member = interaction.user

        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.edit_message(
                content="1. Only Moderator and EMC Faculty can approve documents.",
                view=None,
            )
            return

        ok, error = promote_draft(
            self.draft_filename,
        )

        if not ok:
            await interaction.response.edit_message(
                content=f"1. Approval failed.\n\n2. {error}",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"✅ **{self.draft_filename}** was approved.\n\n"
                "It is now part of EM Bot's verified knowledge base and can be used by `/ask`."
            ),
            view=None,
        )

    @discord.ui.button(
        label="Reject & Delete",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
    )
    async def reject(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        member = interaction.user

        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.edit_message(
                content="1. Only Moderator and EMC Faculty can reject documents.",
                view=None,
            )
            return

        ok, error = reject_draft(
            self.draft_filename,
        )

        if not ok:
            await interaction.response.edit_message(
                content=f"1. Rejection failed.\n\n2. {error}",
                view=None,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"🗑️ **{self.draft_filename}** was rejected and removed.\n\n"
                "The source PDF/CSV/JSON and its draft extraction were deleted."
            ),
            view=None,
        )


class DraftSelect(discord.ui.Select):
    def __init__(self) -> None:
        drafts = draft_documents()

        options = [
            discord.SelectOption(
                label=p.name[:100],
                value=p.name,
                description="Open a preview and approve/reject.",
            )
            for p in drafts[:25]
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="No draft documents",
                    value="__none__",
                    description="Upload a PDF to create a draft.",
                )
            ]

        super().__init__(
            placeholder="Select a document for review...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not drafts,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        filename = self.values[0]

        if filename == "__none__":
            await interaction.response.send_message(
                "1. There are no draft documents to review.",
                ephemeral=True,
            )
            return

        draft_path = DRAFT_DIR / filename

        try:
            content = draft_path.read_text(
                encoding="utf-8",
            )
        except OSError:
            await interaction.response.send_message(
                "1. I couldn't read that draft.",
                ephemeral=True,
            )
            return

        preview = content[:3500]

        if len(content) > 3500:
            preview += "\n\n...[preview truncated]"

        await interaction.response.send_message(
            f"📄 **Draft Review: {filename}**\n\n"
            f"```text\n{preview}\n```\n\n"
            "Review the extracted information carefully before approving it.",
            view=DraftReviewView(filename),
            ephemeral=True,
        )


class KnowledgeManagerView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=300)

        if draft_documents():
            self.add_item(
                DraftSelect()
            )


class Knowledge(commands.Cog):




    @app_commands.command(
        name="knowledge_test",
        description="Staff: test exactly how /ask will retrieve official knowledge.",
    )
    @app_commands.describe(
        question="Question to test against official knowledge.",
    )
    async def knowledge_test(
        self,
        interaction: discord.Interaction,
        question: str,
    ) -> None:
        member = interaction.user

        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can test knowledge retrieval.",
                ephemeral=True,
            )
            return

        curriculum_results = (
            retrieve_structured_curriculum(question)
            if retrieve_structured_curriculum
            else []
        )
        generic_results = (
            retrieve_verified_json_knowledge(question)
            if retrieve_verified_json_knowledge
            else []
        )

        if curriculum_results:
            primary_results = curriculum_results
            route = "DIRECT CURRICULUM JSON"
        elif generic_results:
            primary_results = generic_results
            route = "DIRECT VERIFIED JSON"
        else:
            fallback = (
                retrieve_knowledge(question)
                if retrieve_knowledge
                else []
            )
            primary_results = fallback
            route = "KNOWLEDGE FALLBACK" if fallback else "NO MATCH"

        if not primary_results:
            await interaction.response.send_message(
                "1. **NO MATCH** — no official JSON/knowledge source matched this question.\n\n"
                "2. `/ask` should report that verified information is unavailable.",
                ephemeral=True,
            )
            return

        first = primary_results[0]

        source_match = re.search(
            r"^SOURCE(?: DOCUMENT)?:\s*(.+)$",
            first,
            flags=re.MULTILINE,
        )
        category_match = re.search(
            r"^CATEGORY:\s*(.+)$",
            first,
            flags=re.MULTILINE,
        )
        status_match = re.search(
            r"^STATUS:\s*(.+)$",
            first,
            flags=re.MULTILINE,
        )

        source_name = source_match.group(1).strip() if source_match else "unknown"
        category = category_match.group(1).strip() if category_match else "unknown"
        status = (
            status_match.group(1).strip()
            if status_match
            else str(
                load_manifest().get(source_name, {}).get("status", "unknown")
            )
        )

        fields = re.findall(r'"field":\s*"([^"]+)"', first)
        if not fields:
            fields = re.findall(r'"code":\s*"([^"]+)"', first)

        values = re.findall(r'"value":\s*"([^"]*)"', first)
        field_preview = ", ".join(fields[:8]) if fields else "matched source"
        if len(fields) > 8:
            field_preview += f", +{len(fields) - 8} more"

        answer_preview = (
            " | ".join(values[:5])
            if values
            else re.sub(r"\s+", " ", first)[:650]
        )
        if len(answer_preview) > 700:
            answer_preview = answer_preview[:700] + "..."

        await interaction.response.send_message(
            "1. **MATCHED** — `/ask` has an official knowledge source.\n\n"
            f"2. **Expected source:** `{source_name}`\n\n"
            f"3. **Category:** `{category}`\n\n"
            f"4. **Status used:** **{str(status).upper()}**\n\n"
            f"5. **Route:** `{route}`\n\n"
            f"6. **Expected fields:** `{field_preview}`\n\n"
            f"7. **Expected answer data:** {answer_preview}",
            ephemeral=True,
        )

    @app_commands.command(
        name="knowledge_rebuild_structured",
        description="Staff: rebuild verified JSON/CSV knowledge only.",
    )
    async def knowledge_rebuild_structured(
        self,
        interaction: discord.Interaction,
    ) -> None:
        member = interaction.user

        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can rebuild structured knowledge.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        manifest = load_manifest()
        processed = 0
        failed = 0

        for source in sorted(SOURCE_DIR.iterdir()):
            if not source.is_file():
                continue

            if source.suffix.casefold() not in {".json", ".csv"}:
                continue

            try:
                await process_source_file(
                    source,
                    manifest,
                    force=True,
                    verified=True,
                )
                processed += 1
            except Exception as error:
                failed += 1
                print(
                    f"Structured knowledge rebuild failed for "
                    f"{source.name}: {error}"
                )

        await interaction.followup.send(
            f"1. Structured knowledge rebuild finished.\n\n"
            f"2. Reprocessed: **{processed}**.\n\n"
            f"3. Failed: **{failed}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="knowledge_rebuild",
        description="Staff: reprocess all stored official documents.",
    )
    async def knowledge_rebuild(
        self,
        interaction: discord.Interaction,
    ) -> None:
        member = interaction.user

        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can rebuild the knowledge base.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        manifest = load_manifest()
        processed = 0
        failed = 0

        for source in sorted(SOURCE_DIR.iterdir()):
            if not source.is_file():
                continue
            if source.suffix.casefold() not in {".pdf", ".csv"}:
                continue

            try:
                await process_source_file(
                    source,
                    manifest,
                    force=True,
                )
                processed += 1
            except Exception as error:
                failed += 1
                print(
                    f"Knowledge rebuild failed for {source.name}: {error}"
                )

        await interaction.followup.send(
            f"1. Knowledge rebuild finished.\n\n"
            f"2. Reprocessed: **{processed}**.\n\n"
            f"3. Failed: **{failed}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="knowledge",
        description="Staff: open the EM Bot knowledge manager.",
    )
    async def knowledge(
        self,
        interaction: discord.Interaction,
    ) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can open the knowledge manager.",
                ephemeral=True,
            )
            return

        view = KnowledgePanelView()

        drafts = draft_documents()
        draft_text = (
            f"\n\n⚠️ **Pending review: {len(drafts)}**\n"
            "Use the review panel below to inspect PDF extractions before they become authoritative."
            if drafts
            else "\n\n✅ **No pending document reviews.**"
        )

        await interaction.response.send_message(
            view.panel_text() + draft_text,
            view=view,
            ephemeral=True,
        )

        if drafts:
            await interaction.followup.send(
                "📋 **Pending Document Review**",
                view=KnowledgeManagerView(),
                ephemeral=True,
            )

        all_docs = generic_manager_documents()

        if all_docs:
            current = [
                p.name
                for p in all_docs
                if document_metadata(p.name).get("status") == "current"
            ]

            await interaction.followup.send(
                (
                    "📚 **Knowledge Manager**\n\n"
                    f"**Documents:** {len(all_docs)}\n"
                    f"**Current:** {len(current)}\n\n"
                    "Select any official document to manage its category and status."
                ),
                view=GenericKnowledgeManagerView(),
                ephemeral=True,
            )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await rebuild_missing_or_changed()

    @app_commands.command(
        name="knowledge_add",
        description="Staff: upload a PDF, CSV, or JSON knowledge document.",
    )
    @app_commands.describe(
        attachment="PDF, CSV, or JSON document",
        category="Category such as curriculum, admissions, rules, faq, events, policies, or auto.",
    )
    async def knowledge_add(
        self,
        interaction: discord.Interaction,
        attachment: discord.Attachment,
        category: str = "auto",
    ) -> None:
        member = interaction.user

        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can add knowledge documents.",
                ephemeral=True,
            )
            return

        name = attachment.filename.casefold()

        if not (
            name.endswith(".pdf")
            or name.endswith(".csv")
            or name.endswith(".json")
        ):
            await interaction.response.send_message(
                "1. Only PDF, CSV, and JSON files are supported.",
                ephemeral=True,
            )
            return

        if attachment.size > MAX_FILE_BYTES:
            await interaction.response.send_message(
                f"1. File is too large. Maximum is {MAX_FILE_BYTES // (1024 * 1024)} MB.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
        )

        try:
            data = await attachment.read()

            selected_category = (
                category.strip().casefold()
                if category
                else "auto"
            )

            if selected_category == "auto":
                selected_category = ""

            source_path = SOURCE_DIR / attachment.filename
            source_path.write_bytes(data)

            manifest = load_manifest()

            inferred_data = None
            if attachment.filename.casefold().endswith(".json"):
                try:
                    candidate = json.loads(
                        data.decode("utf-8-sig")
                    )
                    if isinstance(candidate, dict):
                        inferred_data = candidate
                except (UnicodeDecodeError, json.JSONDecodeError):
                    inferred_data = None

            detected_category = (
                selected_category
                or infer_document_category(
                    attachment.filename,
                    inferred_data,
                )
            )

            if detected_category not in CATEGORY_CHOICES:
                detected_category = "other"

            # Structured formats are treated as verified because they are
            # supplied as explicit structured knowledge rather than AI-derived
            # PDF extraction.
            if name.endswith(".csv") or name.endswith(".json"):
                result = await process_source_file(
                    source_path,
                    manifest,
                    force=True,
                    verified=True,
                )

                status = "verified"

                if name.endswith(".json"):
                    try:
                        structured = json.loads(
                            data.decode("utf-8-sig")
                        )
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        structured = None

                    if isinstance(structured, dict):
                        category = infer_document_category(
                            attachment.filename,
                            structured,
                        )
                        entry = manifest.setdefault(
                            attachment.filename,
                            {},
                        )
                        entry["category"] = category
                        entry["scope"] = str(
                            structured.get("major", "")
                            or structured.get("program", "")
                            or ""
                        )

                        # Keep the old behavior for curriculum documents,
                        # but initialize all other structured documents as verified.
                        if category == "curriculum":
                            status = ensure_curriculum_status(
                                attachment.filename,
                                structured,
                            )
                        elif category in SINGLE_CURRENT_CATEGORIES:
                            existing_current = any(
                                item.get("category") == category
                                and item.get("status") == "current"
                                for name, item in manifest.items()
                                if name != attachment.filename
                            )
                            status = "verified" if existing_current else "current"
                            entry["status"] = status
                            manifest[attachment.filename] = entry
                            save_manifest(manifest)
                        else:
                            status = entry.get("status", "verified")
                            entry["status"] = status
                            manifest[attachment.filename] = entry
                            save_manifest(manifest)

                entry = manifest.setdefault(
                    attachment.filename,
                    {}
                )
                entry["category"] = detected_category
                entry.setdefault(
                    "scope",
                    str(
                        inferred_data.get("major", "")
                        or inferred_data.get("program", "")
                        or ""
                    )
                    if isinstance(inferred_data, dict)
                    else ""
                )
                manifest[attachment.filename] = entry
                save_manifest(manifest)

                if detected_category == "curriculum" and isinstance(inferred_data, dict):
                    status = ensure_curriculum_status(
                        attachment.filename,
                        inferred_data,
                    )

                if status == "current":
                    availability = "It is **CURRENT** and will be used for matching current questions in this category."
                else:
                    availability = (
                        "It is **VERIFIED**, but it is not current yet. "
                        "Open `/knowledge` → Curriculum Manager → **Set as Current** "
                        "when you want it to become the active curriculum."
                    )

                await interaction.followup.send(
                    f"1. Added `{attachment.filename}` as **verified knowledge**.\n\n"
                    f"2. Processing result: **{result}**.\n\n"
                    f"3. Status: **{status.upper()}**.\n\n"
                    f"4. {availability}",
                    ephemeral=True,
                )
                return

            # PDFs are deliberately drafts until a staff member reviews them.
            result = await process_source_file(
                source_path,
                manifest,
                force=True,
                verified=False,
            )

            manifest = load_manifest()
            entry = manifest.setdefault(
                attachment.filename,
                {}
            )
            entry["category"] = detected_category
            entry.setdefault(
                "scope",
                ""
            )
            manifest[attachment.filename] = entry
            save_manifest(manifest)

            await interaction.followup.send(
                f"1. Added `{attachment.filename}` as a **draft**.\n\n"
                f"2. AI extraction result: **{result}**.\n\n"
                "3. It is NOT available to `/ask` yet.\n\n"
                "4. Open `/knowledge` and review the extracted content before approving it.",
                ephemeral=True,
            )

        except Exception as error:
            await interaction.followup.send(
                f"1. I couldn't process that document: `{type(error).__name__}`.\n\n"
                "2. Check the bot console for the detailed error.",
                ephemeral=True,
            )



    @app_commands.command(
        name="knowledge_export",
        description="Staff: export the complete knowledge base as a ZIP backup.",
    )
    async def knowledge_export(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can export the knowledge base.",
                ephemeral=True,
            )
            return

        data = build_backup_zip_bytes()
        if len(data) > 8 * 1024 * 1024:
            await interaction.response.send_message(
                "1. The knowledge backup is too large to send through Discord.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "1. Here is your complete EM Bot knowledge backup.",
            file=discord.File(
                io.BytesIO(data),
                filename="EM_Bot_Knowledge_Backup.zip",
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="knowledge_export_md",
        description="Staff: export generated Markdown knowledge files.",
    )
    async def knowledge_export_md(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can export knowledge.",
                ephemeral=True,
            )
            return

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in CACHE_DIR.glob("*.md"):
                archive.write(path, path.name)
        buffer.seek(0)

        await interaction.response.send_message(
            "1. Here are the generated Markdown files.",
            file=discord.File(
                buffer,
                filename="EM_Bot_Knowledge_MD.zip",
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="knowledge_import",
        description="Staff: restore a complete EM Bot knowledge backup.",
    )
    @app_commands.describe(
        attachment="EM Bot knowledge backup ZIP",
    )
    async def knowledge_import(
        self,
        interaction: discord.Interaction,
        attachment: discord.Attachment,
    ) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.send_message(
                "1. Only Moderator and EMC Faculty can import the knowledge base.",
                ephemeral=True,
            )
            return

        if not attachment.filename.casefold().endswith(".zip"):
            await interaction.response.send_message(
                "1. Please upload an EM Bot knowledge backup ZIP.",
                ephemeral=True,
            )
            return

        if attachment.size > 8 * 1024 * 1024:
            await interaction.response.send_message(
                "1. The backup is too large to import through Discord.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            data = await attachment.read()
            valid, error = validate_backup_zip(data)
            if not valid:
                await interaction.followup.send(
                    f"1. The backup could not be imported.\n\n2. {error}",
                    ephemeral=True,
                )
                return

            restored = restore_backup_zip(data)
            await rebuild_missing_or_changed()

            await interaction.followup.send(
                f"1. Knowledge backup restored successfully.\n\n"
                f"2. Files restored: **{restored}**.\n\n"
                "3. The knowledge cache is ready for `/ask`.",
                ephemeral=True,
            )
        except (OSError, zipfile.BadZipFile) as error:
            await interaction.followup.send(
                f"1. The backup restore failed.\n\n2. `{error}`",
                ephemeral=True,
            )

    @app_commands.command(name="knowledge_list", description="Staff: list knowledge documents.")
    async def knowledge_list(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not is_staff(member):
            await interaction.response.send_message("1. Only Moderator and EMC Faculty can view the knowledge base.", ephemeral=True)
            return
        files = sorted(SOURCE_DIR.iterdir()) if SOURCE_DIR.exists() else []
        if not files:
            await interaction.response.send_message("1. The knowledge base is empty.", ephemeral=True)
            return
        await interaction.response.send_message(
            "\n".join(f"{i}. `{p.name}`" for i, p in enumerate(files, 1) if p.is_file()),
            ephemeral=True,
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Knowledge(bot))
