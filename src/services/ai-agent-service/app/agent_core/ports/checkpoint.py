"""CheckpointStore portu.

Veri: LangGraph state checkpoint kayıt/okuma — A0 §5; kalıcı gerçekleştirim
A8'de ``agent_core.checkpoint.FileCheckpointStore`` ile verildi (dev; dosya
tabanlı, çalışma dizini altında). Payload çekirdek tarafından serileştirilen
opak bayt dizisidir; port içeriği çözümlemez — zarf, şema sürümü ve yürütme
kimliği bağlaması çekirdek tarafında ``agent_core.checkpoint`` katmanıdır.

Hata türleri: ``not_found`` (checkpoint yok), ``provider_error``, ``timeout``.

A8 SÖZLEŞMELERİ (plan A8):

- **Kalıcılık:** gerçekleştirim süreç restart'ında checkpoint'i korumak
  ZORUNDADIR; bellek içi saklama bu portun arkasına geçemez [LG-PERSISTENCE#C2].
  Checkpoint saklamak durmuş süreci yeniden başlatmaz: devam ettirmeyi dış
  çalışma adaptörü, uygun checkpoint'i yükleyerek yapar.
- **Eşzamanlı yazım DESTEKLENMEZ:** run başına tek yazar sözleşmesi geçerlidir.
  Aynı run'a eşzamanlı ikinci ``save`` uygulama tarafından algılanıp açık
  hatayla reddedilir; süreçler arası tek yazarlığı dış çalışma adaptörü
  (worker lease/fencing — B6) garanti eder. Desteklenmeyen durum sessiz
  üzerine yazma olarak tanımlanmaz.
- **Bağlama:** yürütme kimliği (``execution_id``) dış adaptörün atadığı ve
  doğruladığı KARARLI kimliktir; checkpoint'in çalıştırma zincirine bağlanması
  zarf katmanının (``agent_core.checkpoint``) işidir, port opak kalır.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["CheckpointStore"]


@runtime_checkable
class CheckpointStore(Protocol):
    """Run bazında checkpoint saklayan port."""

    async def save(self, run_id: str, checkpoint_id: str, payload: bytes) -> None:
        """Checkpoint'i yazar; aynı kimliğe yeniden yazma üzerine yazar.

        Eşzamanlılık: aynı run'a bu örnek üzerinden eşzamanlı ikinci yazım
        desteklenmez; gerçekleştirim ``PortError(validation_error)`` ile
        bildirir (A8 sözleşmesi — modül docstring'i).
        """
        ...

    async def load(self, run_id: str, checkpoint_id: str) -> bytes:
        """Belirli checkpoint'i okur.

        Raises:
            PortError: ``not_found`` — checkpoint bulunamadı;
                ``provider_error``/``timeout`` — depo arızası.
        """
        ...

    async def load_latest(self, run_id: str) -> tuple[str, bytes]:
        """Run'ın en son yazılan checkpoint'ini ``(checkpoint_id, payload)`` döndürür.

        Raises:
            PortError: ``not_found`` — run için checkpoint yok.
        """
        ...
