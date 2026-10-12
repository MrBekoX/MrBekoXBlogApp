"""A10 değerlendirme paketi: küme (dataset) + ölçüm koşucusu.

Bu paket, plan A10'un istediği agent kalite değerlendirmesini taşır:

- **Küme:** ``evals.dataset`` — en az 40 örnek; GERÇEK makale içerikleriyle
  (``evals.articles``) ve bağımsız etiketlenmiş beklenen davranışlarla.
  Örnekler router kurallarının kopyası DEĞİLDİR: etiketler her örnek için
  davranışsal gerekçesiyle (``rationale``) elle yazarılmıştır ve kural
  modülünden türetilmez.
- **Koşucu:** ``evals.harness`` + ``evals.run`` — görev/mod karar doğruluğu,
  ilgili bölümün bulunması, iddia–kanıt desteği + hatalı kaynak oranı,
  fast/analysis gecikmesi, araştırma başına araç/model kullanımı,
  checkpoint'ten devam başarısı, bütçe/iptal davranışı ölçümleri.
- **Önbellek sözleşmesi:** ``evals.cache_policy`` — içerik hash'i, dil, soru
  kapsamı ve yapılandırma sürümlerini taşıyan cevap önbelleği anahtar
  kuralı; konuşmaya bağlı cevaplar ortak önbelleğe girmez.

**Sağlayıcı işaretlemesi:** Ortamda GERÇEK LLM/embedding/arama sağlayıcısı
YOKTUR. Koşucu tüm model/embedding/arama erişimi için ``evals.providers``
altındaki ``is_test_double`` işaretli sağlayıcıları kullanır; üretilen her
rapor ``provider="test_executor"`` ile işaretlenir. Test sağlayıcıyla
koşulan sonuçlar gerçek sağlayıcı başarısı SAYILMAZ (A10 kabul ölçütü).

Geliştirme fixture'larıyla ilişki: ``tests/`` altındaki fixture'lar (küçük
"Merhaba Dünya" makalesi, tests/qa helpers) geliştirme testlerinedir; bu
paketin makaleleri ve sağlayıcıları BAĞIMSIZDIR ve ``tests.*`` modülü
import etmez (A10: "Geliştirme fixture'larını ve değerlendirme örneklerini
ayır").

Çalıştırma (hizmet kökünden)::

    python -m evals.run --suite all --report out/evals
    python -m evals.run --suite routing --list
"""

from __future__ import annotations

from ._paths import ensure_service_paths

# ``evals`` doğrudan kaynak-ağaçtan çalışır (pip kurulumu değildir):
# agent_core'un bulunduğu ``app/`` ve hizmet kökü sys.path'te olmak zorundadır.
# Saf sys.path kurulumudur; agent_core import etmez (yan etkisiz ilk import).
ensure_service_paths()

__all__ = ["ensure_service_paths"]
__version__ = "1.0.0"
