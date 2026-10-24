"""Ortam değişkeni yardımcıları: ``.env`` dosyası yükleme + tür dönüşümü.

Sıfır bağımlılık katmanı: python-dotenv/pydantic-settings GEREKTİRMEZ; yalnız
stdlib. ``service_main`` (source-run), ``messaging`` ayar okuyucuları,
``agent_core.adapters`` from_env fonksiyonları ve alembic ``migrations/env.py``
bu modülü kullanır. Paketleme (``agent_core*``/``messaging*``) bu modülü
içermez: source-run katmanında kalır ve testler üst seviye modül olarak
import eder (pyproject ``pythonpath = ["app"]``).

Yükleme kuralı (``load_env_file``):

1. **Yol:** ``path`` verilmezse ``AGENT_ENV_FILE`` ortam değişkenine bakılır;
   set edilmişse gösterilen dosya YOKSA ``EnvFileError`` yükselir (mesaj
   değişken adını verir, yolu/değerleri yazmaz). Hâlâ None ise bu modülün
   bulunduğu ``app`` dizininden hizmet köküne (``pyproject.toml``'un bulunduğu
   dizin) kadar sırayla ``.env`` aranır (tam ad; ``.env.example`` asla;
   kök/üst dizinlerdeki ilgisiz ``.env``'ler yüklenmez) — CWD'ye bağımlı
   değil, mutlak yol sabitlemesi yok.
   Dosya bulunamazsa sessizce boş dict döner: ``.env`` ZORUNLU DEĞİLDİR;
   üretim ortam değişkenlerini dışarıdan verebilir.
2. **Ayrıştırma:** ``utf-8-sig`` (BOM toleransı); satır bazlı; boş satır ve
   ``#`` ile başlayan yorum satırları atlanır; baştaki opsiyonel ``export ``
   sökülür; ``=`` içermeyen (veya anahtarı boş olan) satır atlanır ve
   yalnız SATIR NUMARASI uyarıyla bildirilir (anahtar/değer yazılmaz — değer
   hassas olabilir). Değerin çevresindeki eş ``'`` veya ``"`` tırnakları
   sökülür; KAÇIŞ ve değişken interpolasyonu YOKTUR (değerler birebir alınır).
   Aynı anahtar dosyada birden çok kez geçerse son satır kazanır.
3. **Öncelik:** yalnız ``os.environ``'da OLMAYAN anahtarlar set edilir
   (setdefault semantiği) — gerçek ortam > ``.env`` > kod varsayılanı. Yalnız
   yeni uygulanan anahtarlar dict olarak döndürülür; ikinci çağrı doğal olarak
   boş döner (idempotent).

Tür dönüşümü (``env_int``/``env_float``/``env_bool``): değer yok/boş/sadece
boşluk ise default döner; dönüşüm başarısızsa ``EnvConfigError`` yükselir ve
mesaj SADECE değişken adını + beklenen türü taşır — HAM DEĞER mesaja
yazılmaz (değer bir sır olabilir).

Bu modülün hiçbir çıktısına (istisna mesajı, log satırı) ortam DEĞERİ
yazılmaz; sır sızıntısı yüzeyi sıfırdır.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

__all__ = ["EnvConfigError", "EnvFileError", "env_bool", "env_float", "env_int", "load_env_file"]

logger = logging.getLogger(__name__)

#: ``.env`` yolunun dışarıdan verilebildiği değişken (``load_env_file`` adım 1).
_ENV_FILE_VAR = "AGENT_ENV_FILE"

#: ``env_bool`` doğru kabul edilen değerler (büyük-küçük duyarsız, strip'li).
_TRUTHY = frozenset({"1", "true", "yes", "on"})

#: ``env_bool`` yanlış kabul edilen değerler (büyük-küçük duyarsız, strip'li).
_FALSY = frozenset({"0", "false", "no", "off"})


class EnvFileError(RuntimeError):
    """``.env`` dosya konumu hatalarında yükselir (ör. ``AGENT_ENV_FILE`` yolu yok)."""


class EnvConfigError(ValueError):
    """Ortam değişkeni tür dönüşümü başarısız olduğunda yükselir.

    Mesaj yalnız değişken adını ve beklenen türü içerir; ham değer hiçbir
    koşulda mesaja yazılmaz (değer hassas olabilir).
    """


def env_int(name: str, default: int, environ: Mapping[str, str] | None = None) -> int:
    """``name`` değişkenini int'e çevirir; yok/boşsa ``default`` döner.

    Raises:
        EnvConfigError: Değer bir tam sayıya çevrilemiyorsa (mesaj ham değer
            içermez).
    """

    raw = _raw(name, environ)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise EnvConfigError(f"'{name}' bir tam sayı olmalıdır (int)") from None


def env_float(name: str, default: float, environ: Mapping[str, str] | None = None) -> float:
    """``name`` değişkenini float'a çevirir; yok/boşsa ``default`` döner.

    Raises:
        EnvConfigError: Değer bir ondalıklı sayıya çevrilemiyorsa (mesaj ham
            değer içermez).
    """

    raw = _raw(name, environ)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise EnvConfigError(f"'{name}' bir ondalıklı sayı olmalıdır (float)") from None


def env_bool(name: str, default: bool, environ: Mapping[str, str] | None = None) -> bool:
    """``name`` değişkenini bool'a çevirir; yok/boşsa ``default`` döner.

    Doğru: ``1/true/yes/on``; yanlış: ``0/false/no/off`` (büyük-küçük duyarsız).

    Raises:
        EnvConfigError: Değer bilinen doğru/yanlış kümelerinden birinde değilse
            (mesaj ham değer içermez).
    """

    raw = _raw(name, environ)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    raise EnvConfigError(
        f"'{name}' bir mantıksal değer olmalıdır (bool): 1/true/yes/on veya 0/false/no/off"
    )


def load_env_file(path: str | None = None) -> dict[str, str]:
    """``.env`` dosyasını bulur, ayrıştırır ve ``os.environ``'a uygular.

    Args:
        path: Açık dosya yolu; verilmezse ``AGENT_ENV_FILE`` ortam değişkeni,
            o da yoksa bu modülün bulunduğu dizinden yukarı doğru ``.env``
            araması kullanılır (bkz. modül docstring'i).

    Returns:
        Yalnız bu çağrıda ``os.environ``'a yeni yazılan anahtar/değer çiftleri.
        Dosya bulunamazsa boş dict (hata DEĞİL); ikinci çağrı idempotent
        olarak boş döner.

    Raises:
        EnvFileError: Açık yol (``path`` veya ``AGENT_ENV_FILE``) verildiği
            hâlde dosya bulunamıyorsa; mesaj yolu/değerleri yazmaz.
    """

    explicit = path if path is not None else os.environ.get(_ENV_FILE_VAR)
    if explicit is not None:
        # Container/CI environments can explicitly disable dotenv discovery.
        # Only the operating system's null device receives this special case;
        # arbitrary missing paths remain configuration errors.
        if explicit == os.devnull:
            return {}
        if not Path(explicit).is_file():
            raise EnvFileError(
                f"'{_ENV_FILE_VAR}' ile gösterilen .env dosyası bulunamadı; "
                "yolu mutlak veya hizmet köküne göre geçerli bir dosya olarak verin"
            )
        return _apply(Path(explicit))

    # app dizininden hizmet köküne kadar '.env' ara (tam ad; .env.example asla).
    # Bulunamazsa sessiz boş dict: dosya zorunlu değil (üretim env'i dışarıdan verir).
    for directory in _search_dirs():
        candidate = directory / ".env"
        if candidate.is_file():
            return _apply(candidate)
    return {}


def _search_dirs() -> list[Path]:
    """Keşif zinciri: bu modülün dizininden hizmet köküne kadar (dâhil).

    Hizmet kökü, ``pyproject.toml`` barındıran ilk ata dizindir; arama onun
    üstündeki (repo/sürücü kökü gibi) ilgisiz ``.env`` dosyalarına inmez.
    """

    chain: list[Path] = []
    for directory in Path(__file__).resolve().parents:
        chain.append(directory)
        if (directory / "pyproject.toml").is_file():
            break
    return chain


def _raw(name: str, environ: Mapping[str, str] | None) -> str | None:
    """Değişkenin ham değerini döndürür; yok/boş/sadece boşluk ise None."""

    env = os.environ if environ is None else environ
    value = env.get(name)
    if value is None or not value.strip():
        return None
    return value


def _apply(env_path: Path) -> dict[str, str]:
    """Dosyayı satır satır ayrıştırır; setdefault semantiğiyle uygular.

    Aynı anahtar dosyada birden çok kez geçerse son satır kazanır (klasik
    ``.env`` davranışı); uygulama aşamasında yalnız ``os.environ``'da olmayan
    anahtarlar yazılır (gerçek ortam .env'i ezer).
    """

    parsed: dict[str, str] = {}
    with env_path.open(encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            key, separator, value = line.partition("=")
            key = key.strip()
            if not separator or not key:
                # '=' içermeyen veya anahtarı boş satır: yalnız konumu bildirilir
                # (anahtar/değer yazılmaz — değer hassas olabilir).
                logger.warning(".env dosyasının %d. satırı ayrıştırılamadı; satır atlandı", line_number)
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            parsed[key] = value

    applied: dict[str, str] = {}
    for key, value in parsed.items():
        if key in os.environ:
            continue  # gerçek ortam .env'i ezer (setdefault semantiği)
        os.environ[key] = value
        applied[key] = value
    return applied
