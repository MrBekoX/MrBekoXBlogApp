# ai-agent-service — Python agent çekirdeği ve değerlendirme paketi

MrBekoX blogunun ziyaretçi agent çekirdeği (`app/agent_core`), transport
bağımsız iş modelleri/portları ve A10 kalite değerlendirme paketi (`evals/`).
Python 3.13 + Pydantic v2 + LangGraph; transport yok — uygulama haberleşmesi
RabbitMQ adaptörüyle (B4/B6/B7/B9, `app/messaging`) yapılır ve bu paketin
giriş noktalarını çağırır (bkz. `docs/entry-points.md`).

```
app/agent_core/          # çekirdek: models, ports, entrypoints, qa, analysis,
                         # research, web, checkpoint, collab, guidance, content, budget
evals/                   # A10 değerlendirme kümesi (61 örnek) + ölçüm koşucusu
tests/                   # pytest paketi (duman + birim + gerçek-broker entegrasyonu)
docs/                    # teslim belgeleri: portlar, yapılandırma, giriş noktaları,
                         # state/şema sürümleri, değerlendirme raporu
```

## Hızlı başlangıç (yerel test girdileriyle)

Gerçek LLM/embedding sağlayıcısı GEREKMEZ: çekirdek tüm model erişimini
portlardan alır ve `agent_core.adapters.test_doubles` + `evals.providers`
altındaki `is_test_double` işaretli sağlayıcılarla koşar. **Test sağlayıcı
sonucu gerçek sağlayıcı başarısı sayılmaz; üretimde gerçek sağlayıcı
bağlanmadan hiçbir kalite iddiası yapılmaz.**

```bash
# 1) Değerlendirme kümesini koş (hizmet kökünden):
cd src/services/ai-agent-service
python -m evals.run --suite all --report out/evals
#   → out/evals/eval-report.json + eval-report.md (provider=test_executor işaretli)
python -m evals.run --list                 # 61 örneklik kümeyi listele
python -m evals.run --suite routing        # tek suite

# 2) Değerlendirme koşucusunun duman testleri:
python -m pytest src/services/ai-agent-service/tests/evals -q

# 3) Paketin tam regresyonu (broker/DB isteyen dizinler hariç; L009 gereği SERİ):
python -m pytest src/services/ai-agent-service/tests -q \
  --ignore=src/services/ai-agent-service/tests/messaging_broker \
  --ignore=src/services/ai-agent-service/tests/intake \
  --ignore=src/services/ai-agent-service/tests/events \
  --ignore=src/services/ai-agent-service/tests/worker \
  --ignore=src/services/ai-agent-service/tests/control \
  --ignore=src/services/ai-agent-service/tests/content_sync \
  --ignore=src/services/ai-agent-service/tests/collab
```

## Paketi kullanma: üç giriş noktası

Haberleşme adaptörü (ve kendi denemeleriniz) yalnız üç fonksiyon çağırır —
tam imzalar ve çağrı sözleşmeleri `docs/entry-points.md`'de:

```python
import asyncio
from agent_core.adapters.test_doubles import FakeModelProvider  # ÜRETİMDE GERÇEK SAĞLAYICI
from agent_core.entrypoints import prepare_and_route, execute_plan
from agent_core.models import BudgetProfile, ExecutionContext

context = ExecutionContext(
    run_id="run-1",
    conversation_id="conv-1",
    question="Asyncio kuyruğunda önerilen üst sınır aralığı kaçtır?",
    language="tr",
    budget_profile=BudgetProfile(
        name="default", max_model_calls=2,
        max_total_tokens=8000, max_duration_seconds=120.0,
    ),
    # article_id / article_revision / article_content_hash / article_snapshot
    # backend doğrulamalı makale bağlamıyla verilir (D008).
)

async def main() -> None:
    prepared = await prepare_and_route(context)          # rota kararı BİR KEZ hesaplanır
    outcome = await execute_plan(                        # kararı yeniden hesaplamaz
        prepared,
        model=FakeModelProvider(),                       # üretimde: gerçek ModelProvider
        # retriever=..., web_tools=..., budget=..., checkpoint=...,
        # profile_repository=..., project_repository=..., article_catalog=...,
    )
    print(outcome.status, outcome.selected_mode, (outcome.answer or outcome.report or "")[:80])

asyncio.run(main())
```

`resume` üçüncü giriş noktasıdır: checkpoint'ten sürer, rota kararını
yeniden hesaplamaz (A8/A9; iş birliği zinciri `docs/entry-points.md` §3'te
uçtan uca örneklidir).

## Belgeler

| Belge | İçerik |
| --- | --- |
| `docs/entry-points.md` | Haberleşme adaptörünün çağıracağı giriş noktaları + çağrı sözleşmeleri |
| `docs/port-contracts.md` | 11 portun sözleşme özeti + veri tipleri |
| `docs/configuration.md` | Yapılandırma rehberi: bütçe profilleri, akış yapılandırmaları, web ayarları, önbellek anahtar kuralı |
| `docs/state-schema-versions.md` | State/şema sürümleri ve uyumluluk kuralları |
| `docs/evals.md` | Değerlendirme kümesi, ölçümler ve rapor sözlüğü |
| `docs/evals-report.md` | Son koşumun raporu (üretilen; `python -m evals.run` ile yenilenir) |

## Sınırlar (dürüst teslim)

- Ortamda GERÇEK LLM/embedding/web-arama sağlayıcısı yoktur; tüm ölçümler
  `provider="test_executor"` işaretlidir.
- pgvector gerçek entegrasyonu B11 kapsamındadır (A3 şeması + adaptör
  sözleşmesi hazır; bellek-içi indeks koşuların tamamında kullanıldı).
- Dosya tabanlı checkpoint store tek-süreç/tek-host varsayımıyla geçerlidir (D016).
