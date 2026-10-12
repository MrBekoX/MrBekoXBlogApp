"""Dosya tabanlı ``CheckpointStore`` gerçekleştirimi (A8 — dev).

Port arkasında KALICI saklama: checkpoint'ler çalışma dizini altındaki bir
klasörde atomik yazıyla (tmp + ``os.replace``) tutulur; süreç yeniden
başladığında aynen okunmaya devam eder — bellek içi saver'ın aksine süreç
restart'ı checkpoint'leri kaybetmez [LG-PERSISTENCE#C2]. Bu, plan A8'in
"Checkpoint saklamak, durmuş Python sürecini yeniden başlatmaz" ilkesine
göre yalnız depolama katmanıdır: süreci yeniden başlatıp uygun checkpoint'le
çağıran dış çalışma adaptörüdür (B6 worker).

DERECE: dev. Üretim arkayolu (DB/Redis) aynı portu doldurur; agent tabloları
Alembic şemasıyla (D011/D014) B6 iş şemasından ayrık tutulur — bu fazda
DB-backed checkpoint bilinçli olarak kurulmadı.

EŞZAMANLILIK SÖZLEŞMESİ (plan A8: "Aynı checkpoint'e eşzamanlı yazmayı
desteklemediğin durumları açık sözleşmeyle bildir"):

- **Run başına TEK yazar.** Aynı run'a ikinci bir eşzamanlı ``save``
  algılanırsa ``PortError(validation_error)`` YÜKSELİR; sessiz üzerine yazma
  yarışı tanımsız davranış değildir, açıkça reddedilir.
- Algılama kapsamı bu depo ÖRNEĞİ içindedir (thread/task ayrımı gözetmez):
  aynı dizini paylaşan iki örnek veya iki süreç bu sözleşmenin kapsamı
  dışındadır; süreçler arası tek yazarlığı dış çalışma adaptörü garanti eder
  (B6 worker lease/fencing — bu fazın kapsamı değildir).
- Okumalar yazı kilidine ihtiyaç duymaz: payload ve manifest atomik
  ``os.replace`` ile yayınlanır; okur en eski tutarlı sürümü ya da hiç görür.
- Farklı run'ların yazıları birbirini asla etkilemez.

Dizin düzeni::

    <base>/<run_id>/manifest.json                  # yazım sırası kaydı
    <base>/<run_id>/<seq>-<checkpoint_id>.bin      # opak payload

``run_id``/``checkpoint_id`` dosya yolu güvenli biçime zorlanır; separator ve
``..`` gibi kimlikler ``validation_error`` ile reddedilir (yol geçişi yok).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from pathlib import Path

from ..errors import AgentErrorCode, PortError

__all__ = ["DEFAULT_CHECKPOINT_DIR", "FileCheckpointStore"]

#: Dev varsayılan kökü: çalışma dizini altında, .gitignore kapsamına alınması
#: beklenen klasör (raporda orchestrator takibi kayıtlı).
DEFAULT_CHECKPOINT_DIR = ".agent_checkpoints"

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_MANIFEST_NAME = "manifest.json"


def _require_safe_id(value: str, *, what: str) -> str:
    stripped = value.strip()
    if _SAFE_ID.match(stripped) is None:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            f"{what} dosya deposu için güvenli değil: {value!r} "
            f"(kalıp: {_SAFE_ID.pattern}; yol ayırıcı ve '..' kabul edilmez)",
            port="FileCheckpointStore",
        )
    return stripped


def _file_name_for(checkpoint_id: str, seq: int) -> str:
    # Windows dosya adları ':' kabul etmez; kimlikteki ayırıcılar alt çizgiye
    # iner. Sıra öneki kimlikleri benzersiz kılar; eşleme manifest'tedir.
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", checkpoint_id)
    return f"{seq:06d}-{sanitized}.bin"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class FileCheckpointStore:
    """Run bazında checkpoint'i dosya sisteminde kalıcı saklayan depo.

    ``CheckpointStore`` portunu (A1) yapısal olarak doldurur; payload için
    opak bayt sözleşmesini korur. Test double DEĞİLDİR: dev gerçekleştirimi
    olduğu için ``is_test_double`` işareti TAŞIMAZ.
    """

    def __init__(self, base_dir: str | os.PathLike[str] | None = None) -> None:
        self._base = Path(base_dir) if base_dir is not None else Path.cwd() / DEFAULT_CHECKPOINT_DIR
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # -- iç düzen ---------------------------------------------------------

    def _run_dir(self, run_id: str) -> Path:
        safe = _require_safe_id(run_id, what="run_id")
        return self._base / safe

    def _read_manifest(self, run_dir: Path) -> list[dict[str, str]]:
        try:
            raw = (run_dir / _MANIFEST_NAME).read_bytes()
        except FileNotFoundError:
            return []
        try:
            document = json.loads(raw.decode("utf-8"))
            entries = document["entries"]
            if not isinstance(entries, list):
                raise TypeError("entries liste olmalıdır")
            return entries
        except (ValueError, UnicodeDecodeError, KeyError, TypeError) as error:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"checkpoint manifest'i bozuk: {run_dir / _MANIFEST_NAME} ({error})",
                port="FileCheckpointStore",
            ) from error

    def _write_manifest(self, run_dir: Path, entries: list[dict[str, str]]) -> None:
        payload = json.dumps({"entries": entries}, ensure_ascii=False).encode("utf-8")
        _atomic_write_bytes(run_dir / _MANIFEST_NAME, payload)

    def _lock_for(self, run_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.Lock())

    # -- port yöntemleri ---------------------------------------------------

    async def save(self, run_id: str, checkpoint_id: str, payload: bytes) -> None:
        """Checkpoint'i atomik yazar; aynı kimliğe yeniden yazma üzerine yazar.

        Eşzamanlılık sözleşmesi: bu örnek üzerinde aynı run'ı hedefleyen
        ikinci eşzamanlı ``save`` reddedilir (modül docstring'ine bakın).

        Raises:
            PortError: ``validation_error`` — güvenli olmayan kimlik veya
                eşzamanlı yazı; ``provider_error`` — disk/manifest arızası.
        """
        safe_run = _require_safe_id(run_id, what="run_id")
        safe_checkpoint = _require_safe_id(checkpoint_id, what="checkpoint_id")
        run_dir = self._base / safe_run
        lock = self._lock_for(safe_run)
        if not lock.acquire(blocking=False):
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"eşzamanlı checkpoint yazısı desteklenmez: run={run_id} için zaten bir "
                "yazım sürüyor (sözleşme: run başına tek yazar; süreçler arası tek "
                "yazarlığı dış çalışma adaptörü garanti eder)",
                port="FileCheckpointStore",
            )
        try:
            # Planlayıcıya teslim: yarışın gerçekten gözlemlenebilir olması için
            # kilidi tutarken yield edilir (sözleşmenin test edilebilirliği).
            await asyncio.sleep(0)
            try:
                run_dir.mkdir(parents=True, exist_ok=True)
                entries = self._read_manifest(run_dir)
                seq = len(entries) + 1
                file_name = _file_name_for(safe_checkpoint, seq)
                _atomic_write_bytes(run_dir / file_name, bytes(payload))
                entries.append(
                    {
                        "checkpoint_id": safe_checkpoint,
                        "file": file_name,
                        "seq": str(seq),
                    }
                )
                self._write_manifest(run_dir, entries)
            except OSError as error:
                raise PortError(
                    AgentErrorCode.PROVIDER_ERROR,
                    f"checkpoint yazılamadı: {run_dir} ({error})",
                    port="FileCheckpointStore",
                ) from error
        finally:
            lock.release()

    async def load(self, run_id: str, checkpoint_id: str) -> bytes:
        """Belirli checkpoint'i okur.

        Raises:
            PortError: ``not_found`` — manifest/payload yok; ``validation_error``
                — güvenli olmayan kimlik; ``provider_error`` — manifest bozuk.
        """
        run_dir = self._run_dir(run_id)
        safe_checkpoint = _require_safe_id(checkpoint_id, what="checkpoint_id")
        entries = self._read_manifest(run_dir)
        for entry in reversed(entries):
            if entry.get("checkpoint_id") == safe_checkpoint:
                file_name = entry.get("file", "")
                return self._read_payload(run_dir, file_name, run_id, safe_checkpoint)
        raise PortError(
            AgentErrorCode.NOT_FOUND,
            f"checkpoint bulunamadı: run={run_id} checkpoint={checkpoint_id}",
            port="FileCheckpointStore",
        )

    async def load_latest(self, run_id: str) -> tuple[str, bytes]:
        """Run'ın en son yazılan checkpoint'ini ``(checkpoint_id, payload)`` döndürür.

        Raises:
            PortError: ``not_found`` — run için checkpoint yok.
        """
        run_dir = self._run_dir(run_id)
        entries = self._read_manifest(run_dir)
        if not entries:
            raise PortError(
                AgentErrorCode.NOT_FOUND,
                f"run için checkpoint yok: {run_id}",
                port="FileCheckpointStore",
            )
        last = entries[-1]
        checkpoint_id = last.get("checkpoint_id", "")
        payload = self._read_payload(run_dir, last.get("file", ""), run_id, checkpoint_id)
        return checkpoint_id, payload

    def _read_payload(
        self, run_dir: Path, file_name: str, run_id: str, checkpoint_id: str
    ) -> bytes:
        if not file_name or "/" in file_name or "\\" in file_name or ".." in file_name:
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                f"manifest dosya adı güvenli değil: {file_name!r}",
                port="FileCheckpointStore",
            )
        try:
            return (run_dir / file_name).read_bytes()
        except FileNotFoundError:
            raise PortError(
                AgentErrorCode.NOT_FOUND,
                f"checkpoint bulunamadı: run={run_id} checkpoint={checkpoint_id} "
                f"(manifest girdisi var, payload dosyası yok: {file_name})",
                port="FileCheckpointStore",
            ) from None
