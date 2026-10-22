"""Canonical profil deposu: ``ProfileKnowledgeRepository`` + legacy ``ProfileRepository``.

``CanonicalProfileRepository`` gerçek, paketlenebilir adaptördür (test double
DEĞİL). Kaynak her erişimde tembel olarak yeniden doğrulanır: önbellek
anahtarı iki dosyanın boyut + mtime değeridir ve yükleme hash'i yeniden
hesaplar. Böylece:

- aynı snapshot tekrar tekrar ayrıştırılmaz;
- dosya bozulursa / geri çekilirse bir sonraki çalışma ``config_error`` alır
  (servis çökmez, bozuk kaynak önbellekten sunulmaz);
- ``load(snapshot)`` pinlenmiş sürüm aktif değilse ``ProfileSourceError``
  yükseltir — worker sessizce başka sürüme GEÇMEZ.

Legacy A9 yolu (v1 run'lar) için ``get_profile()`` canonical kaynaktan
türetilmiş ``ProfileSummary`` döndürür: açıklama FAQ'taki üçüncü şahıs
cevaplarından + eğitim satırından (≤4000), yetkinlikler ``skills``
bölümünün maddelerinden, bağlantılar yayımlanmış ``contact_channels``'tan.
SEO anahtar kelimesi veya elle yazılmış ikinci biyografi kopyası kullanılmaz.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from ..models import ProfileSnapshotRef
from ..ports.profile import ProfileSummary
from .source import MANIFEST_FILE, ProfileDocument, ProfileSourceError, load_profile_source

__all__ = ["CanonicalProfileRepository", "profile_summary_from_document"]

_DESCRIPTION_LIMIT = 4000
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_BULLET_PREFIX_RE = re.compile(r"^\s*[-*]\s+")


def _strip_markdown(text: str) -> str:
    return _BOLD_RE.sub(r"\1", _BULLET_PREFIX_RE.sub("", text)).strip()


def _bounded_join(parts: list[str], limit: int) -> str:
    """Parçaları sınır içinde birleştirir; sınırı aşan parça eklenmez (yarım cümle yok)."""

    output: list[str] = []
    length = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        extra = len(part) + (2 if output else 0)
        if length + extra > limit:
            break
        output.append(part)
        length += extra
    return "\n\n".join(output)


def profile_summary_from_document(document: ProfileDocument) -> ProfileSummary:
    """Canonical belgeden legacy A9 ``ProfileSummary``'si türetir (uydurma yok)."""

    parts: list[str] = []
    faq = document.section("faq")
    if faq is not None:
        # FAQ cevapları üçüncü şahıstır: agent kendini Sample olarak tanıtmaz.
        # Kalın soru satırı (**...?**) özete girmez; yalnız cevap metni alınır.
        for paragraph in faq.body.split("\n\n"):
            lines = [line for line in paragraph.splitlines() if line.strip()]
            if lines and lines[0].lstrip().startswith("**") and lines[0].rstrip().endswith("**"):
                lines = lines[1:]
            answer = _strip_markdown(" ".join(lines))
            if answer:
                parts.append(answer)
    education = document.section("education")
    if education is not None:
        parts.append(_strip_markdown(education.body))
    description = _bounded_join(parts, _DESCRIPTION_LIMIT) or None

    skills: list[str] = []
    skills_section = document.section("skills")
    if skills_section is not None:
        for line in skills_section.body.splitlines():
            cleaned = _strip_markdown(line)
            if cleaned:
                skills.append(cleaned)

    links: dict[str, str] = {}
    for channel in document.privacy.contact_channels:
        key = "site" if channel.kind == "website" else channel.kind
        links.setdefault(key, channel.url)

    return ProfileSummary(
        name=document.owner.name,
        job_title=None,
        description=description,
        links=links,
        skills=skills,
        updated_at=document.content_created_datetime(),
    )


class CanonicalProfileRepository:
    """Canonical dosya kaynağını okuyan gerçek adaptör (``ProfileKnowledgeRepository``).

    Aynı nesne legacy ``ProfileRepository`` portunu da karşılar (``get_profile``).
    """

    is_test_double = False

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._lock = threading.Lock()
        self._fingerprint: tuple | None = None
        self._document: ProfileDocument | None = None
        #: Gerçekleşen tam yükleme (ayrıştırma + hash) sayısı; önbellek testleri ölçer.
        self.load_count = 0

    @property
    def directory(self) -> Path:
        return self._directory

    def _stat_fingerprint(self) -> tuple:
        entries: list[tuple] = []
        manifest = self._directory / MANIFEST_FILE
        for path in (manifest,):
            try:
                stat = path.stat()
            except OSError:
                raise ProfileSourceError(f"profil kaynağı dosyası bulunamadı: {MANIFEST_FILE}") from None
            entries.append((path.name, stat.st_size, stat.st_mtime_ns))
        # İçerik dosyası adı manifest'ten gelir; tüm dizindeki .json dosyalarının
        # parmak izi alınır (yeni sürüm yazıldığında önbellek düşer).
        try:
            others = sorted(p for p in self._directory.glob("*.json") if p.name != MANIFEST_FILE)
        except OSError:
            others = []
        for path in others:
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((path.name, stat.st_size, stat.st_mtime_ns))
        return tuple(entries)

    def current_document(self) -> ProfileDocument:
        """Aktif (doğrulanmış) belgeyi döndürür; dosya değiştiyse yeniden doğrular.

        Raises:
            ProfileSourceError: kaynak eksik/bozuk/hash uyumsuz/public değil.
        """

        with self._lock:
            fingerprint = self._stat_fingerprint()
            if self._document is not None and fingerprint == self._fingerprint:
                return self._document
            # Bozuk kaynak önbellekten sunulmaz: önce eski kayıt düşürülür.
            self._document = None
            self._fingerprint = None
            document = load_profile_source(self._directory)
            self.load_count += 1
            self._document = document
            self._fingerprint = fingerprint
            return document

    # --- ProfileKnowledgeRepository ---

    def active_snapshot(self) -> ProfileSnapshotRef:
        return self.current_document().snapshot

    def load(self, snapshot: ProfileSnapshotRef) -> ProfileDocument:
        """Pinlenmiş sürümün belgesini döndürür; aktif sürüm farklıysa hata.

        Raises:
            ProfileSourceError: kaynak kullanılamıyor veya pinlenmiş sürüm artık aktif değil.
        """

        document = self.current_document()
        if not document.snapshot.same_as(snapshot):
            raise ProfileSourceError(
                "bu çalışmaya sabitlenen profil sürümü artık aktif değil "
                f"(sabitlenen revizyon {snapshot.revision}, aktif revizyon {document.snapshot.revision}); "
                "güncel profille yeni bir soru sorun"
            )
        return document

    # --- legacy ProfileRepository (A9) ---

    async def get_profile(self) -> ProfileSummary:
        return profile_summary_from_document(self.current_document())
