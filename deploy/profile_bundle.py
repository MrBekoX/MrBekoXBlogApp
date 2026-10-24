"""Prepare/validate a private profile bundle without publishing personal data.

Only this generic tool belongs in Git. Source documents and generated bundles
must stay outside Git and Docker build contexts. Runtime mounts supply the same
read-only bundle to the API and worker; embedding vectors are never stored here.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import unicodedata
from urllib.parse import urlsplit


MAX_BYTES = 2_000_000
_IDS = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
_HEADINGS = {
    "kisaca": ("overview", "bio"),
    "egitim ve kariyer yolum": ("education", "bio"),
    "teknik yetkinliklerim": ("skills", "bio"),
    "projelerim": ("projects", "project"),
    "yapay zeka ve ajan calismalarim": ("ai-work", "ai_work"),
    "acik kaynak katkim xerj corpus hub": ("oss-xerj", "oss"),
    "mimari konusundaki yaklasimim": ("architecture", "bio"),
    "blogda ne yaziyorum": ("blog-topics", "bio"),
    "sertifikalarim": ("certificates", "bio"),
    "calisma tarzim": ("working-style", "bio"),
    "kisisel ilgi alanlarim": ("interests", "bio"),
    "neleri paylasmiyorum": ("privacy-scope", "policy"),
    "iletisim": ("contact", "contact"),
    "sik sorulan sorular": ("faq", "faq"),
}
_ENGLISH_ALIASES = {
    "overview": ["who", "about", "biography", "summary", "background", "profession"],
    "education": ["education", "university", "degree", "internship", "teaching", "career", "instructor"],
    "skills": ["skills", "technologies", "languages", "frameworks", "backend", "frontend"],
    "projects": ["projects", "portfolio", "applications", "repositories"],
    "ai-work": ["AI", "agents", "RAG", "agentic", "automation", "research"],
    "oss-xerj": ["open source", "contribution", "XERJ"],
    "architecture": ["architecture", "design", "clean", "onion", "CQRS"],
    "blog-topics": ["blog", "topics", "articles", "writing"],
    "certificates": ["certificates", "certifications", "courses"],
    "working-style": ["working style", "approach", "workflow"],
    "interests": ["interests", "hobbies", "music", "sports"],
    "privacy-scope": ["privacy", "disclosure", "private information"],
    "contact": ["contact", "website", "github", "linkedin", "social"],
    "faq": ["frequently asked questions", "introduction"],
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold().replace("ı", "i"))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalized.encode("ascii", "ignore").decode()).split())


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        return stream.read(MAX_BYTES + 1)


def validate_bundle(directory: str | Path, *, require_production: bool = True) -> list[str]:
    """Return safe validation errors without echoing identities or source text."""
    root = Path(directory)
    try:
        manifest_bytes = _read_bounded(root / "manifest.json")
        profile_bytes = _read_bounded(root / "profile.json")
        source_bytes = _read_bounded(root / "source/author-profile.source.md")
        if any(not value or len(value) > MAX_BYTES for value in (manifest_bytes, profile_bytes, source_bytes)):
            return ["Profile files must be nonempty and within the size limit"]
        manifest, profile = json.loads(manifest_bytes), json.loads(profile_bytes)
        if not isinstance(manifest, dict) or not isinstance(profile, dict):
            return ["Profile metadata must contain JSON objects"]
        if manifest.get("manifest_schema") != 1 or profile.get("schema") != "author-profile/1":
            return ["Unsupported profile bundle schema"]
        if manifest.get("content_file") != "profile.json" or manifest.get("status") != "public" or manifest.get("approved") is not True:
            return ["Profile must be explicitly approved for the public agent"]
        if manifest.get("profile_id") != profile.get("profile_id") or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", str(profile.get("profile_id", ""))):
            return ["Invalid or mismatched profile identity"]
        if type(manifest.get("revision")) is not int or manifest["revision"] < 1:
            return ["Profile revision must be a positive integer"]
        if manifest.get("content_hash") != hashlib.sha256(profile_bytes).hexdigest():
            return ["Profile content hash does not match its manifest"]
        source = manifest.get("source", {})
        if not isinstance(source, dict) or source.get("file") != "source/author-profile.source.md" or source.get("sha256") != hashlib.sha256(source_bytes).hexdigest():
            return ["Original profile source hash does not match its manifest"]
        owner = profile.get("owner", {})
        if not isinstance(owner, dict) or not isinstance(owner.get("name"), str) or not owner["name"].strip():
            return ["A profile owner identity is required"]
        if manifest.get("language") != profile.get("language") or profile.get("language") != "tr":
            return ["Profile languages must match the approved source"]
        sections = profile.get("sections")
        if not isinstance(sections, list) or not sections:
            return ["Approved profile sections are required"]
        seen = set()
        for section in sections:
            if not isinstance(section, dict):
                return ["Invalid profile section"]
            key = section.get("section_id")
            if not isinstance(key, str) or not _IDS.fullmatch(key) or key in seen or section.get("anchor") != key:
                return ["Profile section identity or anchor is invalid"]
            seen.add(key)
            if not isinstance(section.get("body"), str) or not section["body"].strip():
                return ["Profile section content is required"]
            if not isinstance(section.get("title"), dict) or not section["title"].get("tr") or not section["title"].get("en") or not section.get("heading_path"):
                return ["Profile section headings are required"]
            if not isinstance(section.get("kind"), str) or not section["kind"].strip():
                return ["Profile section kind is required"]
            if not isinstance(section.get("notes", []), list) or not all(isinstance(note, str) for note in section.get("notes", [])):
                return ["Invalid profile section notes"]
        privacy = profile.get("privacy", {})
        if not isinstance(privacy, dict):
            return ["Invalid profile privacy configuration"]
        for field, allowed in (
            ("undisclosed_topics", {"current_employer", "client_projects", "job_applications", "personal_contact_details"}),
            ("unknown_fields", {"age", "birth_date", "salary", "marital_status", "total_years_experience", "rates", "availability"}),
        ):
            values = privacy.get(field, [])
            if not isinstance(values, list) or not all(isinstance(value, str) and value in allowed for value in values):
                return ["Unrecognized profile privacy category"]
        for channel in privacy.get("contact_channels", []):
            if not isinstance(channel, dict):
                return ["Invalid profile contact channel"]
            parsed = urlsplit(str(channel.get("url", "")))
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                return ["Profile contact channels must be public HTTPS links"]
        if not any(section.get("retrievable", True) for section in sections):
            return ["Profile has no retrievable sections"]
        if require_production and (
            profile.get("profile_id") == "sample-author" or _fold(owner["name"]) in {"sample author", "example author"}
            or "example.invalid" in profile_bytes.decode("utf-8").casefold()
        ):
            return ["Production requires an approved real profile bundle, not the repository example"]
        return []
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return ["Profile bundle is missing, unreadable or malformed"]


def _private_destination(output: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    if output.is_relative_to(repo) and (repo / ".git").exists():
        relative = (output / "profile.json").relative_to(repo)
        ignored = subprocess.run(["git", "check-ignore", "--quiet", str(relative)], cwd=repo).returncode == 0
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(relative)], cwd=repo,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not ignored or tracked:
            raise ValueError("Private profile output must be Git-ignored and untracked")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Profile output must be a new or empty private directory; existing data is never overwritten")


def build_bundle(source: Path, output: Path, *, as_of: str, revision: int, approved: bool) -> None:
    if not approved:
        raise ValueError("Explicit public-agent source approval is required")
    date.fromisoformat(as_of)
    if revision < 1:
        raise ValueError("Profile revision must be positive")
    source_bytes = _read_bounded(source)
    if not source_bytes or len(source_bytes) > MAX_BYTES:
        raise ValueError("Approved source is empty or too large")
    text = source_bytes.decode("utf-8-sig")
    identity = re.search(r"^#\s+[^\r\n:]+:\s*([^\r\n]+)", text, re.M)
    if identity is None:
        raise ValueError("Source must identify its owner in the first Markdown heading")
    name = identity.group(1).strip()
    aliases = [name, name.split()[0]]
    for alias in re.findall(r"(?:çevrimiçi adım|online name|alias)\s+([^).\n]+)", text, re.I):
        aliases.append(alias.strip())
    headings = list(re.finditer(r"^## (.+?)\r?$", text, re.M))
    sections = []
    for index, heading in enumerate(headings):
        title = heading.group(1).strip()
        body = text[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(text)].strip()
        if not body:
            continue
        key, kind = _HEADINGS.get(_fold(title), (_fold(title).replace(" ", "-")[:128], "bio"))
        sections.append({
            "section_id": key, "anchor": key, "kind": kind, "heading_path": [title],
            "title": {"tr": title, "en": title},
            "aliases": {"tr": _fold(title).split(), "en": _ENGLISH_ALIASES.get(key, [])},
            "body": body, "claim": {"kind": "self_statement", "as_of": as_of, "temporal": "as_of"},
            "notes": [], "retrievable": True,
        })
    contact = next((section["body"] for section in sections if section["section_id"] == "contact"), "")
    channels = []
    for url in dict.fromkeys(re.findall(r"https://[^\s<>()\]\"']+", contact)):
        parsed = urlsplit(url)
        if parsed.username or parsed.password or not parsed.hostname or parsed.query or parsed.fragment:
            continue
        host = parsed.hostname.casefold()
        kind = "github" if host == "github.com" else "linkedin" if host.endswith("linkedin.com") else "x" if host in {"x.com", "twitter.com"} else "website"
        channels.append({"kind": kind, "label": kind, "url": url.rstrip(".,;")})
    profile_id = "owner-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:20]
    profile = {
        "schema": "author-profile/1", "profile_id": profile_id, "language": "tr",
        "owner": {"name": name, "aliases": list(dict.fromkeys(aliases))},
        "privacy": {"undisclosed_topics": ["current_employer", "client_projects", "job_applications", "personal_contact_details"],
                    "unknown_fields": ["age", "birth_date", "salary", "marital_status", "total_years_experience", "rates", "availability"],
                    "contact_channels": channels},
        "sections": sections,
    }
    profile_bytes = _json_bytes(profile)
    manifest = {"manifest_schema": 1, "profile_id": profile_id, "revision": revision, "language": "tr",
                "content_file": "profile.json", "content_hash": hashlib.sha256(profile_bytes).hexdigest(),
                "status": "public", "approved": True, "content_created_at": datetime.now(timezone.utc).isoformat(),
                "source": {"file": "source/author-profile.source.md", "sha256": hashlib.sha256(source_bytes).hexdigest(),
                           "received_at": as_of, "verified_at": None}}
    output = output.resolve()
    _private_destination(output)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    (output / "source").mkdir(mode=0o700)
    for path, value in ((output / "profile.json", profile_bytes), (output / "manifest.json", _json_bytes(manifest)),
                        (output / "source/author-profile.source.md", source_bytes)):
        with path.open("xb") as stream:
            stream.write(value)
        path.chmod(0o600)
    if validate_bundle(output):
        raise ValueError("Generated private bundle failed validation; no source text was logged")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate")
    check.add_argument("directory", type=Path)
    build = commands.add_parser("build")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--as-of", required=True)
    build.add_argument("--revision", type=int, default=1)
    build.add_argument("--approved", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "build":
            build_bundle(args.source, args.output, as_of=args.as_of, revision=args.revision, approved=args.approved)
            print("Private profile bundle created and validated; original source bytes preserved.")
            return 0
        errors = validate_bundle(args.directory)
        for error in errors:
            print(error)
        return 1 if errors else 0
    except (OSError, UnicodeError, ValueError):
        print("Profile preparation failed; use an approved source and a new Git-ignored output directory.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
