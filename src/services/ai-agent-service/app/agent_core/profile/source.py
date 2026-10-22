"""Canonical profil kaynağı okuyucusu (Who am I, karar K2).

Tek onaylı, sürümlü public profil kaynağı ``src/content/author-profile``
altındadır: ``manifest.json`` (kimlik + content_hash + yayın durumu) ve
``profile.json`` (bölümler, gizlilik yapılandırması, sahip bilgisi).

Doğrulama sözleşmesi (her okuyucu aynı kuralı uygular):

- ``content_hash`` = ``sha256(profile.json ham byte)``; okuyucu hash'i yeniden
  hesaplar, manifest'le uyuşmazsa kaynak KULLANILAMAZ.
- ``status == "public"`` ve ``approved is True`` olmalıdır (geri çekilmiş /
  onaysız profil sunulmaz).
- ``profile_id`` manifest ile içerikte aynı; şema ``author-profile/1``.
- Bölüm kimlikleri benzersiz ve ``^[a-z0-9][a-z0-9-]{0,127}$``; anchor ==
  section_id (``/about#{section_id}`` sözleşmesi).
- Gizlilik kategori kimlikleri yalnız güvenilen politika modülünün tanıdığı
  değerler olabilir (bilinmeyen kategori uygulanamaz → kaynak reddedilir).

Her hata ``ProfileSourceError`` (``config_error``) olarak yükselir; mesajlar
güvenlidir: dosya içeriği veya mutlak dosya yolu taşımaz.

Yol çözümü (``resolve_profile_dir``): ``AGENT_PROFILE_DIR`` (mutlak yol) →
bu modülün konumundan yukarı yürüyerek ``src/content/author-profile`` (veya
paketlenmiş ``content/author-profile``). Çalışma dizini (cwd) KULLANILMAZ.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import AgentErrorCode, PortError
from ..models import BusinessModel, ProfileSnapshotRef

__all__ = [
    "MANIFEST_FILE",
    "PROFILE_DIR_ENV",
    "PROFILE_SCHEMA",
    "UNDISCLOSED_TOPIC_IDS",
    "UNKNOWN_FIELD_IDS",
    "ContactChannel",
    "PrivacyConfig",
    "ProfileDocument",
    "ProfileOwner",
    "ProfileSection",
    "ProfileSourceError",
    "load_profile_source",
    "resolve_profile_dir",
]

#: Canonical kaynak dizinini açıkça veren ortam değişkeni (mutlak yol).
PROFILE_DIR_ENV = "AGENT_PROFILE_DIR"
MANIFEST_FILE = "manifest.json"
MANIFEST_SCHEMA = 1
PROFILE_SCHEMA = "author-profile/1"

#: Güvenilen gizlilik politikasının tanıdığı kategori kimlikleri
#: (``agent_core.profile.policy`` her birine kalıp taşır).
UNDISCLOSED_TOPIC_IDS = frozenset(
    {"current_employer", "client_projects", "job_applications", "personal_contact_details"}
)
UNKNOWN_FIELD_IDS = frozenset(
    {"age", "birth_date", "salary", "marital_status", "total_years_experience", "rates", "availability"}
)

_SECTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
_URL_RE = re.compile(r"^https://[^\s<>\"']+$")

#: Kaynak dosyaları için üst sınır: bozuk/kötü niyetli büyük dosya belleği şişirmez.
_MAX_FILE_BYTES = 2_000_000

#: Modül konumundan yukarı yürürken aranan göreli dizinler (sırayla).
_CANDIDATE_RELATIVE_DIRS = (
    Path("src") / "content" / "author-profile",
    Path("content") / "author-profile",
)


class ProfileSourceError(PortError):
    """Canonical profil kaynağı kullanılamıyor: ``config_error``.

    ``PortError`` alt sınıfıdır; mevcut terminal eşleme yolları (``run_guidance``,
    runner'lar) hatayı ``failed/config_error`` olarak raporlar. Mesaj güvenlidir:
    dosya içeriği veya mutlak yol taşımaz.
    """

    def __init__(self, message: str) -> None:
        super().__init__(AgentErrorCode.CONFIG_ERROR, message, port="ProfileSource", retryable=False)


class ContactChannel(BusinessModel):
    """Yayımlanmış herkese açık iletişim kanalı (yalnız bunlar önerilir)."""

    kind: str
    label: str
    url: str


class PrivacyConfig(BusinessModel):
    """Güvenilen gizlilik yapılandırması (profile.json ``privacy`` bloğu)."""

    undisclosed_topics: list[str] = []
    unknown_fields: list[str] = []
    contact_channels: list[ContactChannel] = []


class ProfileOwner(BusinessModel):
    name: str
    aliases: list[str] = []


class ProfileSection(BusinessModel):
    """Tek profil bölümü; ``section_id`` aynı zamanda ``/about`` anchor'ıdır."""

    section_id: str
    anchor: str
    kind: str
    heading_path: list[str]
    title: dict[str, str]
    aliases: dict[str, list[str]] = {}
    body: str
    claim: dict[str, Any] = {}
    notes: list[str] = []
    retrievable: bool = True

    def title_for(self, language: str) -> str:
        """Dile göre başlık; İngilizce yoksa Türkçe başlığa düşer."""

        if not language.casefold().startswith("tr") and self.title.get("en"):
            return self.title["en"]
        return self.title.get("tr") or next(iter(self.title.values()))


class ProfileDocument(BusinessModel):
    """Doğrulanmış canonical profil belgesi (pinlenebilir sürüm kimliğiyle)."""

    snapshot: ProfileSnapshotRef
    profile_schema: str
    language: str
    owner: ProfileOwner
    privacy: PrivacyConfig
    sections: list[ProfileSection]
    status: str
    approved: bool
    content_created_at: str | None = None
    source_received_at: str | None = None
    verification: str | None = None

    @property
    def profile_id(self) -> str:
        return self.snapshot.profile_id

    @property
    def revision(self) -> int:
        return self.snapshot.revision

    @property
    def content_hash(self) -> str:
        return self.snapshot.content_hash

    def section(self, section_id: str) -> ProfileSection | None:
        for section in self.sections:
            if section.section_id == section_id:
                return section
        return None

    def retrievable_sections(self) -> list[ProfileSection]:
        return [section for section in self.sections if section.retrievable]

    @property
    def section_ids(self) -> frozenset[str]:
        return frozenset(section.section_id for section in self.sections)

    def content_created_datetime(self) -> datetime | None:
        if not self.content_created_at:
            return None
        try:
            parsed = datetime.fromisoformat(self.content_created_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


# --- yol çözümü ---


def resolve_profile_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Canonical profil dizinini çözer; cwd'ye bağlı değildir.

    Sıra: ``AGENT_PROFILE_DIR`` (mutlak yol, içinde ``manifest.json`` olmalı)
    → bu modülün konumundan yukarı yürüyerek ``src/content/author-profile``
    veya paketlenmiş ``content/author-profile``.

    Raises:
        ProfileSourceError: yapılandırılmış dizin geçersiz veya kaynak bulunamadı.
    """

    env = os.environ if environ is None else environ
    configured = (env.get(PROFILE_DIR_ENV) or "").strip()
    if configured:
        directory = Path(configured)
        if not directory.is_absolute():
            raise ProfileSourceError(
                f"{PROFILE_DIR_ENV} mutlak bir yol olmalıdır (çalışma dizinine göre çözülmez)"
            )
        if not (directory / MANIFEST_FILE).is_file():
            raise ProfileSourceError(f"{PROFILE_DIR_ENV} dizininde {MANIFEST_FILE} bulunamadı")
        return directory

    here = Path(__file__).resolve()
    for parent in here.parents:
        for relative in _CANDIDATE_RELATIVE_DIRS:
            candidate = parent / relative
            if (candidate / MANIFEST_FILE).is_file():
                return candidate
    raise ProfileSourceError(
        "canonical profil kaynağı bulunamadı: "
        f"{PROFILE_DIR_ENV} ayarlayın veya src/content/author-profile/{MANIFEST_FILE} paketleyin"
    )


# --- okuma ve doğrulama ---


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError:
        raise ProfileSourceError(f"profil kaynağı dosyası bulunamadı: {label}") from None
    if size > _MAX_FILE_BYTES:
        raise ProfileSourceError(f"profil kaynağı dosyası çok büyük: {label}")
    try:
        return path.read_bytes()
    except OSError:
        raise ProfileSourceError(f"profil kaynağı dosyası okunamadı: {label}") from None


def _parse_json(raw: bytes, label: str) -> dict[str, Any]:
    if not raw.strip():
        raise ProfileSourceError(f"profil kaynağı dosyası boş: {label}")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ProfileSourceError(f"profil kaynağı dosyası geçerli UTF-8 JSON değil: {label}") from None
    if not isinstance(parsed, dict):
        raise ProfileSourceError(f"profil kaynağı dosyası JSON nesnesi değil: {label}")
    return parsed


def _require_str(value: Any, where: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where} metin olmalı")
    return value


def _require_str_list(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where} metin listesi olmalı")
    return list(value)


def _validate_manifest(manifest: dict[str, Any]) -> tuple[ProfileSnapshotRef, str, dict[str, Any]]:
    if manifest.get("manifest_schema") != MANIFEST_SCHEMA:
        raise ProfileSourceError("manifest.json şema sürümü desteklenmiyor")
    profile_id = manifest.get("profile_id")
    if not isinstance(profile_id, str) or not _PROFILE_ID_RE.match(profile_id):
        raise ProfileSourceError("manifest.json profile_id geçersiz")
    revision = manifest.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ProfileSourceError("manifest.json revision pozitif tam sayı olmalı")
    content_hash = manifest.get("content_hash")
    if not isinstance(content_hash, str) or not _HASH_RE.match(content_hash):
        raise ProfileSourceError("manifest.json content_hash 64 karakterlik küçük harf SHA-256 olmalı")
    content_file = manifest.get("content_file")
    if not isinstance(content_file, str) or not _CONTENT_FILE_RE.match(content_file) or ".." in content_file:
        raise ProfileSourceError("manifest.json content_file geçersiz (yalnız aynı dizindeki .json dosyası)")
    if manifest.get("status") != "public":
        raise ProfileSourceError("profil kaynağı public değil (status != public); sunulamaz")
    if manifest.get("approved") is not True:
        raise ProfileSourceError("profil kaynağı onaylı değil (approved != true); sunulamaz")
    language = manifest.get("language")
    if not isinstance(language, str) or not _LANGUAGE_RE.match(language):
        raise ProfileSourceError("manifest.json language geçersiz")
    snapshot = ProfileSnapshotRef(profile_id=profile_id, revision=revision, content_hash=content_hash)
    return snapshot, content_file, manifest


def _validate_privacy(raw: Any) -> PrivacyConfig:
    if not isinstance(raw, dict):
        raise ProfileSourceError("profil kaynağı şeması geçersiz: privacy nesne olmalı")
    undisclosed = _require_str_list(raw.get("undisclosed_topics", []), "privacy.undisclosed_topics")
    unknown = _require_str_list(raw.get("unknown_fields", []), "privacy.unknown_fields")
    bad_undisclosed = sorted(set(undisclosed) - UNDISCLOSED_TOPIC_IDS)
    if bad_undisclosed:
        raise ProfileSourceError(
            f"privacy.undisclosed_topics bilinmeyen kategori içeriyor: {', '.join(bad_undisclosed)}"
        )
    bad_unknown = sorted(set(unknown) - UNKNOWN_FIELD_IDS)
    if bad_unknown:
        raise ProfileSourceError(f"privacy.unknown_fields bilinmeyen kategori içeriyor: {', '.join(bad_unknown)}")
    channels_raw = raw.get("contact_channels", [])
    if not isinstance(channels_raw, list):
        raise ProfileSourceError("profil kaynağı şeması geçersiz: privacy.contact_channels liste olmalı")
    channels: list[ContactChannel] = []
    for index, item in enumerate(channels_raw):
        where = f"privacy.contact_channels[{index}]"
        if not isinstance(item, dict):
            raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where} nesne olmalı")
        url = _require_str(item.get("url"), f"{where}.url")
        if not _URL_RE.match(url):
            raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where}.url https bağlantısı olmalı")
        channels.append(
            ContactChannel(
                kind=_require_str(item.get("kind"), f"{where}.kind"),
                label=_require_str(item.get("label"), f"{where}.label"),
                url=url,
            )
        )
    return PrivacyConfig(undisclosed_topics=undisclosed, unknown_fields=unknown, contact_channels=channels)


def _validate_section(raw: Any, index: int) -> ProfileSection:
    where = f"sections[{index}]"
    if not isinstance(raw, dict):
        raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where} nesne olmalı")
    section_id = raw.get("section_id")
    if not isinstance(section_id, str) or not _SECTION_ID_RE.match(section_id):
        raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where}.section_id biçimi")
    if raw.get("anchor") != section_id:
        raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where}.anchor section_id ile aynı olmalı")
    heading_path = _require_str_list(raw.get("heading_path"), f"{where}.heading_path")
    if not heading_path:
        raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where}.heading_path boş olamaz")
    title_raw = raw.get("title")
    if not isinstance(title_raw, dict) or not isinstance(title_raw.get("tr"), str) or not title_raw["tr"].strip():
        raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where}.title.tr zorunlu")
    title = {
        key: _require_str(value, f"{where}.title.{key}") for key, value in title_raw.items() if isinstance(key, str)
    }
    aliases_raw = raw.get("aliases", {})
    if not isinstance(aliases_raw, dict):
        raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where}.aliases nesne olmalı")
    aliases = {
        str(key): _require_str_list(value, f"{where}.aliases.{key}") for key, value in aliases_raw.items()
    }
    claim = raw.get("claim", {})
    if not isinstance(claim, dict):
        raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where}.claim nesne olmalı")
    retrievable = raw.get("retrievable", True)
    if not isinstance(retrievable, bool):
        raise ProfileSourceError(f"profil kaynağı şeması geçersiz: {where}.retrievable boolean olmalı")
    return ProfileSection(
        section_id=section_id,
        anchor=section_id,
        kind=_require_str(raw.get("kind"), f"{where}.kind"),
        heading_path=heading_path,
        title=title,
        aliases=aliases,
        body=_require_str(raw.get("body"), f"{where}.body"),
        claim=dict(claim),
        notes=_require_str_list(raw.get("notes", []), f"{where}.notes"),
        retrievable=retrievable,
    )


def load_profile_source(directory: Path) -> ProfileDocument:
    """Manifest + içeriği okur, hash'i yeniden hesaplar ve şemayı doğrular.

    Raises:
        ProfileSourceError: dosya eksik/boş/bozuk, hash uyuşmazlığı, public/onay
            durumu geçersiz, şema/kimlik/bölüm/gizlilik kategorisi hatası.
    """

    directory = Path(directory)
    manifest = _parse_json(_read_bytes(directory / MANIFEST_FILE, MANIFEST_FILE), MANIFEST_FILE)
    snapshot, content_file, manifest = _validate_manifest(manifest)

    raw_content = _read_bytes(directory / content_file, content_file)
    if not raw_content.strip():
        raise ProfileSourceError(f"profil kaynağı dosyası boş: {content_file}")
    actual_hash = hashlib.sha256(raw_content).hexdigest()
    if actual_hash != snapshot.content_hash:
        raise ProfileSourceError(
            f"{content_file} içerik hash'i manifest content_hash ile uyuşmuyor (kaynak bozuk veya yarım güncellenmiş)"
        )
    content = _parse_json(raw_content, content_file)

    if content.get("schema") != PROFILE_SCHEMA:
        raise ProfileSourceError(f"{content_file} şeması desteklenmiyor (beklenen {PROFILE_SCHEMA})")
    if content.get("profile_id") != snapshot.profile_id:
        raise ProfileSourceError(f"{content_file} profile_id manifest ile uyuşmuyor")
    language = content.get("language")
    if language != manifest.get("language"):
        raise ProfileSourceError(f"{content_file} language manifest ile uyuşmuyor")

    owner_raw = content.get("owner")
    if not isinstance(owner_raw, dict):
        raise ProfileSourceError("profil kaynağı şeması geçersiz: owner nesne olmalı")
    owner = ProfileOwner(
        name=_require_str(owner_raw.get("name"), "owner.name"),
        aliases=_require_str_list(owner_raw.get("aliases", []), "owner.aliases"),
    )
    privacy = _validate_privacy(content.get("privacy", {}))

    sections_raw = content.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        raise ProfileSourceError("profil kaynağı şeması geçersiz: sections boş olmayan liste olmalı")
    sections: list[ProfileSection] = []
    seen: set[str] = set()
    for index, item in enumerate(sections_raw):
        section = _validate_section(item, index)
        if section.section_id in seen:
            raise ProfileSourceError(f"profil kaynağı şeması geçersiz: tekrarlanan section_id {section.section_id}")
        seen.add(section.section_id)
        sections.append(section)
    if not any(section.retrievable for section in sections):
        raise ProfileSourceError("profil kaynağında aranabilir (retrievable) bölüm yok")

    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return ProfileDocument(
        snapshot=snapshot,
        profile_schema=PROFILE_SCHEMA,
        language=str(language),
        owner=owner,
        privacy=privacy,
        sections=sections,
        status="public",
        approved=True,
        content_created_at=manifest.get("content_created_at") if isinstance(manifest.get("content_created_at"), str) else None,
        source_received_at=source.get("received_at") if isinstance(source.get("received_at"), str) else None,
        verification=source.get("verification") if isinstance(source.get("verification"), str) else None,
    )
