"""Canonical profil kaynağı + depo testleri (K2; A22, A23, A33 Python tarafı).

Gerçek canonical kaynak ``resolve_profile_dir()`` ile okunur; bozuk, eksik,
hash uyumsuz, geri çekilmiş ve revizyon değişimi senaryoları geçici dizin
kopyalarında üretilir. Hata mesajları güvenlidir (mutlak yol / içerik yok).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from profile_helpers import (
    canonical_dir,
    copy_profile,
    read_json,
    rewrite_profile,
    run,
    section_by_id,
    write_manifest,
)

from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import ProfileSnapshotRef
from agent_core.ports import ProfileKnowledgeRepository, ProfileRepository
from agent_core.profile import (
    PROFILE_DIR_ENV,
    CanonicalProfileRepository,
    ProfileSourceError,
    load_profile_source,
    resolve_profile_dir,
)


def assert_safe_config_error(error: ProfileSourceError, tmp_path: Path) -> None:
    assert isinstance(error, PortError)
    assert error.code is AgentErrorCode.CONFIG_ERROR
    assert error.retryable is False
    assert str(tmp_path) not in error.message  # mutlak yol sızmaz


# --- gerçek canonical kaynak ---


def test_real_canonical_source_loads_and_matches_manifest_hash() -> None:
    directory = canonical_dir()
    manifest = read_json(directory / "manifest.json")
    raw = (directory / "profile.json").read_bytes()

    document = load_profile_source(directory)

    assert document.snapshot.profile_id == manifest["profile_id"] == "sample-author"
    assert document.snapshot.revision == manifest["revision"]
    assert document.snapshot.content_hash == manifest["content_hash"] == hashlib.sha256(raw).hexdigest()
    assert document.status == "public" and document.approved is True
    assert document.owner.name == "Sample Author"
    ids = [section.section_id for section in document.sections]
    assert len(ids) == len(set(ids)) == 25
    assert all(section.anchor == section.section_id for section in document.sections)
    assert {"overview", "education", "teaching", "faq", "privacy-scope", "contact"} <= set(ids)
    assert set(document.privacy.unknown_fields) >= {"age", "salary", "total_years_experience"}


def test_resolve_profile_dir_walks_from_module_not_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(PROFILE_DIR_ENV, raising=False)
    first = resolve_profile_dir({})
    monkeypatch.chdir(tmp_path)  # cwd değişse de çözüm aynı kalır
    second = resolve_profile_dir({})

    assert first == second
    assert (first / "manifest.json").is_file()
    assert first.parts[-2:] == ("content", "author-profile")


def test_resolve_profile_dir_env_override_must_be_absolute_and_valid(tmp_path) -> None:
    target = copy_profile(tmp_path)
    assert resolve_profile_dir({PROFILE_DIR_ENV: str(target)}) == target

    with pytest.raises(ProfileSourceError, match="mutlak"):
        resolve_profile_dir({PROFILE_DIR_ENV: "relative/author-profile"})
    with pytest.raises(ProfileSourceError, match="manifest.json"):
        resolve_profile_dir({PROFILE_DIR_ENV: str(tmp_path / "missing")})


# --- A22: kaynak yok / boş / bozuk / hash uyumsuz / geri çekilmiş ---


def test_hash_mismatch_is_config_error(tmp_path) -> None:
    target = copy_profile(tmp_path)
    (target / "profile.json").write_bytes((target / "profile.json").read_bytes() + b"\n")

    with pytest.raises(ProfileSourceError) as caught:
        load_profile_source(target)
    assert "hash" in caught.value.message
    assert_safe_config_error(caught.value, tmp_path)


@pytest.mark.parametrize(
    ("breaker", "fragment"),
    [
        (lambda d: (d / "manifest.json").unlink(), "bulunamadı"),
        (lambda d: (d / "profile.json").unlink(), "bulunamadı"),
        (lambda d: (d / "profile.json").write_bytes(b""), "boş"),
        (lambda d: (d / "manifest.json").write_text("{bozuk", encoding="utf-8"), "JSON"),
        (lambda d: write_manifest(d, status="withdrawn"), "public"),
        (lambda d: write_manifest(d, approved=False), "onaylı"),
        (lambda d: write_manifest(d, content_file="../profile.json"), "content_file"),
        (lambda d: write_manifest(d, revision=0), "revision"),
    ],
    ids=["no-manifest", "no-profile", "empty-profile", "broken-manifest", "withdrawn", "unapproved", "path-traversal", "bad-revision"],
)
def test_broken_or_withdrawn_source_is_config_error(tmp_path, breaker, fragment) -> None:
    target = copy_profile(tmp_path)
    breaker(target)

    with pytest.raises(ProfileSourceError) as caught:
        load_profile_source(target)
    assert fragment in caught.value.message
    assert_safe_config_error(caught.value, tmp_path)


def _duplicate_section(content: dict) -> None:
    content["sections"].append(dict(content["sections"][0]))


def _bad_section_id(content: dict) -> None:
    content["sections"][0]["section_id"] = "Bad_ID"


def _anchor_mismatch(content: dict) -> None:
    content["sections"][0]["anchor"] = "baska-anchor"


def _unknown_privacy_category(content: dict) -> None:
    content["privacy"]["unknown_fields"].append("shoe_size")


def _profile_id_mismatch(content: dict) -> None:
    content["profile_id"] = "baska-profil"


def _schema_mismatch(content: dict) -> None:
    content["schema"] = "author-profile/99"


def _http_contact(content: dict) -> None:
    content["privacy"]["contact_channels"][0]["url"] = "http://mrbekox.dev"


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (_duplicate_section, "tekrarlanan"),
        (_bad_section_id, "section_id"),
        (_anchor_mismatch, "anchor"),
        (_unknown_privacy_category, "bilinmeyen kategori"),
        (_profile_id_mismatch, "profile_id"),
        (_schema_mismatch, "şema"),
        (_http_contact, "https"),
    ],
    ids=["duplicate", "bad-id", "anchor", "privacy-category", "profile-id", "schema", "contact-url"],
)
def test_schema_violations_with_valid_hash_are_rejected(tmp_path, mutate, fragment) -> None:
    target = copy_profile(tmp_path)
    rewrite_profile(target, mutate)  # hash güncel: yalnız şema kuralı devrede

    with pytest.raises(ProfileSourceError) as caught:
        load_profile_source(target)
    assert fragment in caught.value.message
    assert_safe_config_error(caught.value, tmp_path)


# --- depo: önbellek, pin, revizyon değişimi (A23) ---


def test_repository_implements_knowledge_and_legacy_ports() -> None:
    repository = CanonicalProfileRepository(canonical_dir())
    assert isinstance(repository, ProfileKnowledgeRepository)
    assert isinstance(repository, ProfileRepository)
    assert CanonicalProfileRepository.is_test_double is False


def test_repository_caches_by_fingerprint_without_reparsing() -> None:
    repository = CanonicalProfileRepository(canonical_dir())
    snapshot = repository.active_snapshot()
    for _ in range(5):
        assert repository.load(snapshot).snapshot.same_as(snapshot)
    assert repository.load_count == 1


def test_pinned_snapshot_mismatch_never_switches_version() -> None:
    repository = CanonicalProfileRepository(canonical_dir())
    active = repository.active_snapshot()
    other = ProfileSnapshotRef(profile_id=active.profile_id, revision=active.revision + 1, content_hash="0" * 64)

    with pytest.raises(ProfileSourceError, match="aktif değil"):
        repository.load(other)


def test_revision_change_activates_new_snapshot_and_rejects_old_pin_a23(tmp_path) -> None:
    target = copy_profile(tmp_path)
    repository = CanonicalProfileRepository(target)
    old = repository.active_snapshot()

    def new_education(content: dict) -> None:
        section_by_id(content, "education")["body"] = "- **Eğitim:** Güncellenmiş test kaydı (2000–2004)."

    new_hash = rewrite_profile(target, new_education, revision=old.revision + 1)

    new = repository.active_snapshot()
    assert new.revision == old.revision + 1 and new.content_hash == new_hash
    assert repository.load(new).section("education").body.startswith("- **Eğitim:** Güncellenmiş")
    with pytest.raises(ProfileSourceError, match="aktif değil"):
        repository.load(old)  # eski pinli run sessizce yeni sürüme geçmez
    assert repository.load_count == 2


def test_source_broken_after_caching_is_not_served_stale(tmp_path) -> None:
    target = copy_profile(tmp_path)
    repository = CanonicalProfileRepository(target)
    snapshot = repository.active_snapshot()

    write_manifest(target, status="withdrawn")  # yayından kaldırıldı

    with pytest.raises(ProfileSourceError, match="public"):
        repository.load(snapshot)
    with pytest.raises(ProfileSourceError):
        repository.active_snapshot()


def test_repository_legacy_summary_comes_from_canonical_source() -> None:
    summary = run(CanonicalProfileRepository(canonical_dir()).get_profile())

    assert summary.name == "Sample Author"
    assert summary.description is not None and len(summary.description) <= 4000
    assert "Sample Academy" in summary.description
    assert summary.links["linkedin"].startswith("https://www.example.invalid/")


def test_manifest_and_profile_are_valid_json_files() -> None:
    # Paket/servis dağıtımında okunan dosyalar (A33 Python tarafı): ham byte hash'i sabittir.
    directory = canonical_dir()
    json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    raw = (directory / "profile.json").read_bytes()
    assert b"\r\n" not in raw  # .gitattributes -text: CRLF dönüşümü hash'i bozmaz
