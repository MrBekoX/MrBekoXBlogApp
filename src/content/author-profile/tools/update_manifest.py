"""Canonical yazar profili manifest'ini yeniler.

Kullanim (depo kokunden):
    python src/content/author-profile/tools/update_manifest.py --bump
    python src/content/author-profile/tools/update_manifest.py --check

--bump   profile.json degistiginde revision'i bir artirir, content_hash ve
         content_created_at alanlarini yeniler.
--check  manifest'in profile.json ve ham kaynakla tutarli oldugunu dogrular
         (CI / paketleme oncesi). Tutarsizlikta exit 1.

content_hash, profile.json dosyasinin HAM BYTE'larinin SHA-256 ozetidir. Python,
.NET ve frontend okuyuculari ayni ozeti hesaplar; dosya .gitattributes ile
satir sonu donusumunden korunur.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _write_manifest(manifest: dict) -> None:
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    MANIFEST.write_bytes(text.encode("utf-8"))


def check() -> list[str]:
    manifest = _load_manifest()
    problems: list[str] = []
    content = ROOT / manifest["content_file"]
    if _sha256(content) != manifest["content_hash"]:
        problems.append("content_hash profile.json ile eslesmiyor")
    profile = json.loads(content.read_text(encoding="utf-8"))
    if profile.get("profile_id") != manifest.get("profile_id"):
        problems.append("profile_id manifest ile profile.json arasinda farkli")
    raw = ROOT / manifest["source"]["file"]
    if _sha256(raw) != manifest["source"]["sha256"]:
        problems.append("ham kaynak SHA-256 manifest ile eslesmiyor")
    if profile.get("provenance", {}).get("raw_sha256") != manifest["source"]["sha256"]:
        problems.append("profile.json provenance.raw_sha256 manifest ile eslesmiyor")
    return problems


def bump() -> None:
    manifest = _load_manifest()
    content = ROOT / manifest["content_file"]
    new_hash = _sha256(content)
    if new_hash == manifest["content_hash"]:
        print("profile.json degismemis; revision artirilmadi.")
        return
    manifest["revision"] = int(manifest["revision"]) + 1
    manifest["content_hash"] = new_hash
    manifest["content_created_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_manifest(manifest)
    print(f"revision={manifest['revision']} content_hash={new_hash}")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bump", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.bump:
        bump()
        return 0
    problems = check()
    for problem in problems:
        print(f"HATA: {problem}", file=sys.stderr)
    if not problems:
        print("manifest tutarli")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
