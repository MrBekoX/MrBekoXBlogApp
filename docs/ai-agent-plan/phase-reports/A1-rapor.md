# A1 Faz Raporu — İş modellerini ve agent portlarını oluştur

- **Faz:** A1 (bağımsız Python paketi: iş modelleri, portlar, giriş noktaları)
- **Tarih:** 2026-10-11
- **Branch / temel:** `feature/ai-agent-integration`, HEAD `8f148ab` (= `origin/main`)
- **Rol:** A1 implementasyon agent'ı
- **Ön koşul girdileri:** `docs/ai-agent-plan/agent-architecture.md`, `docs/ai-agent-plan/phase-reports/A0-rapor.md`, `docs/ai-agent-plan/phase-reports/W0-ortak-mimari-kararlari.md`
- **Yazılan dosyalar:** yalnız izinli kapsam — `src/services/ai-agent-service/**` ve bu rapor. `progress.md`, `decisions.md`, backend/frontend kodu ve hiçbir mevcut dosya değiştirilmedi (`git status --short`: yalnız `?? src/services/` yeni).
- **Kapsam dışı bırakılanlar:** LangGraph graph kurulumu (A2), retrieval (A3), broker/AMQP (`app/messaging` B1'de), backend/frontend kodu. Hiçbir commit/push yapılmadı.

## 1. Ortam ve ön koşul doğrulaması

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| Python sürümü | `python --version` | Python 3.13.9 |
| Kurulu bağımlılıklar | `python -m pip show pydantic pytest` | pydantic 2.11.7, pytest 8.3.3 (görevde bildirilenle aynı) |
| Hedef dizin yok | `ls src/`, `ls src/services` | `src/services` mevcut değildi; oluşturuldu (W0 §0 kanıtıyla uyumlu) |
| Kök pytest yapılandırma çakışması | `ls pyproject.toml pytest.ini setup.cfg tox.ini` | Repo kökünde yok; `src/services/ai-agent-service/pyproject.toml` rootdir'i belirler |
| Kaynak arşivi | `node docs/ai-agent-plan/source/tools/search.cjs search --stage A1 …` (2 sorgu) | CONTEXT döndü: [PYDANTIC-MODELS#C1], [PYDANTIC-MODELS#C2], [JSON-SCHEMA#C1], [JSON-SCHEMA#C2], [PY-ASYNCIO#C1], [PY-ASYNCIO#C2], [LG-WORKFLOWS#C1] |

## 2. Oluşturulan paket yapısı

```
src/services/ai-agent-service/
├── pyproject.toml            # setuptools; pydantic>=2.11,<3; [tool.pytest.ini_options] pythonpath=["app"]
├── .gitignore                # __pycache__/, .pytest_cache/, *.pyc
├── app/agent_core/
│   ├── errors.py             # AgentErrorCode (8 ortak kod) + PortError
│   ├── routing.py            # decide_mode/route_for_context: saf, deterministik, model çağrısız
│   ├── entrypoints.py        # PreparedRun, ResumeRequest, prepare_and_route, execute_plan, resume
│   ├── models/               # 13 iş modeli + RunStatus + destek tipleri
│   ├── ports/                # 11 port (Protocol) + port veri tipleri
│   └── adapters/
│       ├── config.py         # ProviderSettings + resolve_*_provider
│       └── test_doubles/     # 13 Fake*/Token/Sink sınıfı, is_test_double işaretli
└── tests/                    # conftest + 5 test modülü (74 test)
```

Paket düzeni W0 §2.1 sahiplik tablosuna birebir uygundur: import kökü `agent_core`, `app/` paket köküdür; `agent_core` hiçbir transport modülünü import etmez (yön: messaging → agent_core, B1'de).

## 3. İş modelleri (13 + RunStatus)

| Model | Dosya | Öne çıkan doğrulama kuralları |
| --- | --- | --- |
| `ExecutionContext` | models/context.py | Alan kümesi plan A1 satırının aynısı; snapshot verildiyse `article_id`/`article_revision`/`article_content_hash` zorunlu ve kimlikleri snapshot ile tutarlı olmalı; `extra="forbid"` |
| `AgentOutcome` | models/outcome.py | `answer`/`report` aynı anda dolu olamaz; completed/partial → answer veya report zorunlu; failed → `error_code` zorunlu; needs_input → `unresolved_questions` dolu olmalı; `action_proposal.run_id == usage.run_id` |
| `RouteDecision` | models/routing.py | `requires_web_search` yalnız `deep_research` modunda true olabilir; `selected_mode` `auto` alamaz (AgentMode enum'unda yok) |
| `ArticleSnapshot` | models/article.py | `content_hash` SHA-256 hex kalıbı; `compute_content_hash()` UTF-8 SHA-256 (A0 §7.2 sözleşmesi) |
| `ArticleChunk` | models/article.py | `char_end >= char_start`; `chunk_index >= 0` (anlamı A3) |
| `SourceReference` | models/sources.py | kind'a göre ayırt edilmiş alan zorunluluğu: article → üçlü tam, url/accessed_at yasak; web → url+accessed_at zorunlu, makale alanları yasak; `source_id` kanonik türetilir (`article:{id}:{rev}:{chunk}` / `web:{sha256(url)[:16]}:{ts}`) |
| `EvidenceItem` | models/sources.py | `SourceReference` + alıntı + zaman |
| `ResearchPlan` | models/research.py | Limit varsayılanları plan A2 önerileri (8 arama, 12 sayfa, 2 tur, 3 eşzamanlı); 1–8 alt soru |
| `ResearchFinding` | models/research.py | `confidence ∈ {low, medium, high}` |
| `DomainProgress` | models/progress.py | `event_sequence` bilinçli olarak YOK (envelope tarafındadır, W0 Ç6); `kind` ProgressKind enum'u |
| `UsageRecord` | models/usage.py | Negatif olmayan sayaçlar |
| `ActionProposal` | models/action.py | `base_content_hash` SHA-256 kalıbı; düzenlenebilir `summary` |
| `ValidatedActionResult` | models/action.py | `accepted` → `applied_article_revision` zorunlu |
| `RunStatus` | models/enums.py | Yalnız `completed, partial, needs_input, cancelled, failed` — teslim/kuyruk durumu yok (plan A1:182; W0 §1.3) |

Ortak taban: `models/base.py` — `BusinessModel` (`extra="forbid"`, `validate_assignment=True`), `UtcDatetime` (naive datetime reddedilir, aware girdi UTC'ye çevrilir), `HashHex`, `LanguageCode`, `Identifier`. Ek-alan politikasının açık yapılandırılması [PYDANTIC-MODELS#C2], doğrulamanın model sınırında yürütülmesi [PYDANTIC-MODELS#C1] ilkesine dayanır.

## 4. Portlar (11) ve hata sözleşmesi

`errors.py`: `AgentErrorCode` — `config_error, validation_error, not_found, stale_snapshot, budget_exhausted, cancelled, provider_error, timeout` (agent-architecture §5 ile aynı küme; W0 §1.5). `PortError(code, message, port, retryable)`.

Portlar `typing.Protocol` + `@runtime_checkable`; her metodun docstring'i verdiği veri ve fırlatacağı hata türlerini taşır:

| Port | Veri | Docstring'de tanımlı hatalar |
| --- | --- | --- |
| `ContentRepository` | `ArticleSnapshot` | not_found, config_error, provider_error, timeout |
| `ProfileRepository` | `ProfileSummary` (port veri tipi) | not_found, config_error, provider_error, timeout |
| `ProjectRepository` | `list[ProjectRecord]` (port veri tipi) | not_found, config_error, provider_error, timeout |
| `ModelProvider` | `ModelRequest` → `ModelResponse` (+`ModelUsage`) | config_error, provider_error, timeout, cancelled |
| `EmbeddingProvider` | `list[list[float]]` (sıra korunur) | validation_error, config_error, provider_error, timeout, cancelled |
| `WebSearchProvider` | `list[WebSearchResult]` | validation_error, config_error, provider_error, timeout, cancelled |
| `SourceReader` | `ReadSource` | not_found, validation_error (özel/metadata adresi), provider_error, timeout, cancelled |
| `CheckpointStore` | opak `bytes` payload | not_found, provider_error, timeout |
| `BudgetStore` | `reserve/commit/release/usage` + `BudgetKind`, `BudgetReservation`, `BudgetUsage` | budget_exhausted, not_found, provider_error, timeout |
| `CancellationToken` | `is_cancelled/reason/raise_if_cancelled` (senkron, süreç içi — A0 §5) | cancelled |
| `ProgressSink` | `DomainProgress` yayımı | provider_error, timeout (yayım arızası akışı kesmez) |

İptal semantiği [PY-ASYNCIO#C2]'ye uygun tasarlandı: `raise_if_cancelled` `PortError(CANCELLED)` fırlatır, terminal haritalamada bastırılmadan sonuca çevrilir. İptal noktaları giriş noktası sınırında (node/araç sınırları A2'nin işidir).

## 5. Uygulama girişleri

- **`prepare_and_route(context, *, progress, cancel, checkpoint) -> PreparedRun`** — iptal kontrolü → `verify_snapshot_binding` (hash'i içerikten **yeniden hesaplar**; uyuşmazsa `stale_snapshot`, A0 §7.2) → ilerleme olayları → `route_for_context` (**saf fonksiyon, model çağrısı yok**; tercihe saygı, auto için deterministik sezgi: seçili metin→analysis, araştırma sinyali/uzun soru→deep_research(+web), açıklama sinyali→analysis, aksi→fast) → checkpoint verilirse `PreparedRun` JSON'unu yazar.
- **`execute_plan(prepared, *, model, budget, progress, cancel) -> AgentOutcome`** — hazır gelen `PreparedRun` ile çalışır, rota **yeniden hesaplamaz** (plan A1:186). Bütçe: `reserve(MODEL_CALL)` → model çağrısı → `commit(fiili token)`; hata/iptalde `release`. Terminal haritalama: `CANCELLED→status=cancelled`, diğer `PortError→status=failed + error_code`. `deep_research` → `report`, diğerleri → `answer`.
- **`resume(request, *, checkpoint, model, budget, progress, cancel) -> AgentOutcome`** — checkpoint'ten `PreparedRun` yükler; rota kararı checkpoint'ten gelir (**router bir daha çağrılmaz**); bozuk payload → `validation_error`, başka run'a ait payload → `validation_error`, yok → `not_found`.

Yönlendirme akışının "girdiyi sınıflandırıp göreve gönderme" kalıbı [LG-WORKFLOWS#C1] notuyla uyumludur; graph'a taşınması A2'dir.

## 6. Test double ↔ gerçek sağlayıcı ayrımı

- Test double'lar yalnız `agent_core/adapters/test_doubles/` altında; her sınıf `is_test_double = True` işareti taşır.
- Üretim çözümleyicisi `adapters/config.py`: bilinmeyen sağlayıcı adı, eksik zorunlu ayar, A1'de uygulanmamış adaptör ve **`environment != "test"` iken test sağlayıcısı istenmesi** — hepsi `config_error` kodlu, sağlayıcı adını/eksik alanı/düzeltmeyi söyleyen insan-okur mesajla reddedilir (ana prompt kritik kontrol: "Test sağlayıcısı üretimde etkinleştirilemez" ikinci katmanla korunur).
- `ProviderSettings` `extra="forbid"`: bilinmeyen yapılandırma anahtarı ValidationError ile reddedilir.

## 7. Gerçek test çıktıları

Komut (repo kökünden, görevde istenen haliyle):

```
python -m pytest src/services/ai-agent-service/tests -q
........................................................................ [ 97%]
..                                                                       [100%]
74 passed in 0.17s
```

Sonuç: **74 passed, 0 failed, 0 skipped** (ortam: Python 3.13.9, pydantic 2.11.7, pytest 8.3.3; .venv oluşturulmadı).

Kapsam dağılımı:
- `test_models_serialization.py` — 13 iş modelinin JSON gidiş-dönüş kimliği, snake_case alan kümesi, JSON-güvenli `model_dump(mode="json")`, kanonik `source_id` türetimi.
- `test_models_validation.py` — 21 red davranışı: fazladan alan (ör. `delivery_state` sızamaz), bilinmeyen `RunStatus`, boş soru, hatalı dil kodu, hatalı hash kalıbı, naive datetime, snapshot kimlik uyuşmazlığı, completed/failed/needs_input durum kuralları, chunk ofsetleri, SourceReference ayrımı, `accepted` sonucunda revizyon zorunluluğu, web bayrağı kuralı, bütçe sıfır limiti, konuşma rolü kısıtı.
- `test_entrypoints.py` — 16 davranış: prepare **hiç model çağırmaz** (ExplodingModelProvider çağrı sayısı 0), tercih saygısı, auto sezgi (research/analysis/fast), `stale_snapshot` iki biçimi (bayat EC hash'i, bozuk snapshot hash'i), yalnız-referans EC'nin geçerliliği (K7), ilerleme olay sırası, iptal (prepare fırlatır / execute terminal `cancelled` üretir), bütçe commit'i (15 token), bütçe tükenmesi (model çağrılmadan `failed`+`budget_exhausted`), sağlayıcı arızasında rezervasyon `release`'i, sink arızasının akışı kesmemesi, resume: rota checkpoint'ten geri yüklenir ve **router tekrar çağrılmaz** (`model.call_count == 1` yalnız tamamlama), not_found / bozuk payload / yabancı-run payload reddi.
- `test_provider_config.py` — 8 yapılandırma davranışı: test sağlayıcısı development/production'da reddedilir, yalnız `environment="test"`'te döner; bilinmeyen ad mesajı bilinenleri listeler; eksik `api_key`/`model_name` alan adlarıyla mesaj; uygulanmamış adaptör için eyleme dönük mesaj; bilinmeyen settings anahtarı reddi; embedding/web çözücülerin aynı sözleşmesi.
- `test_adapters_separation.py` — 4 ayrım davranışı: `test_doubles.__all__` içindeki her sınıf `is_test_double=True`; 11 portun tamamının runtime_checkable Protocol eşleşmesi (`isinstance` kanıtı); `agent_core.adapters` kök ad alanında işaretli sınıf yok.

Ek kontrol: `python -m pyflakes src/services/ai-agent-service/app src/services/ai-agent-service/tests` → temiz (kullanılmayan import/undefined ad yok). pytest-asyncio kurulmadı; async akışlar `conftest.run()` (`asyncio.run`) ile koşar — test bağımlılığı yalnız pytest+pydantic kalır.

## 8. Kabul ölçütleri karşılama (plan A1:190-193)

1. **"Paket dış adaptör olmadan test girdisiyle çağrılabilir."** → **Karşılandı.** `test_entrypoints.py` 16 testi hiçbir dış adaptör olmadan yalnız test double'larla prepare→execute→resume akışlarını koşturur; giriş noktaları yalnız port tipine bağımlıdır.
2. **"İş modelleri serileştirilebilir ve hatalı veriyi reddeder."** → **Karşılandı.** 14 serileştirme + 21 doğrulama testi (§7). `extra="forbid"` + açık alan zorunlulukları [PYDANTIC-MODELS#C1][PYDANTIC-MODELS#C2].
3. **"Sağlayıcı yapılandırma hataları anlaşılırdır."** → **Karşılandı.** 8 `test_provider_config.py` testi; her red `config_error` + sağlayıcı adı/eksik alan/düzeltme içeren insan-okur mesaj.
4. **"Test double ile gerçek sağlayıcı arasındaki ayrım açıktır."** → **Karşılandı.** Ayrı `test_doubles/` paketi + `is_test_double` işareti + Protocol eşleşme kanıtı + üretimde test sağlayıcısı reddi (§6).

Ayrıca plan A1:186 kuralı ("Aynı router kararının yeniden model çağrısıyla hesaplanmasını önle") iki testle kanıtlandı: prepare model çağrısız karar üretir; execute/resume hazır kararı tüketir, resume'da `model.call_count == 1`.

## 9. Kullanılan kaynak kimlikleri (yalnız gerçekten gelen CONTEXT parçaları)

- [PYDANTIC-MODELS#C1] — model sınırında doğrulama/serileştirme, yapılandırılmış hatalar → §3 taban tasarımı ve §7 serileştirme testleri.
- [PYDANTIC-MODELS#C2] — dönüşümün sınırlandırılması, açık alan zorunluluğu ve ek-alan politikası → `extra="forbid"`, açık Optional/varsayılanlar.
- [JSON-SCHEMA#C1], [JSON-SCHEMA#C2] — properties/required/additionalProperties kavramlarının sözleşme okuması → §3 "alan kümesi = sözleşme" ilkesi (JSON Schema dosyası A1 kapsamında üretilmedi; B1'e aittir).
- [PY-ASYNCIO#C1], [PY-ASYNCIO#C2] — iptal istisnasının bastırılmaması, yapılandırılmış eşzamanlılık → `CancellationToken` sözleşmesi ve terminal haritalama (paralel görev eşzamanlılığı A4'ün işidir).
- [LG-WORKFLOWS#C1] — routing akışı → §5 router girişinin biçimi.
- Pydantic 2.11.7 davranış iddiaları (WrapValidator imzası, `extra="forbid"` reddi, naive datetime reddi, UTC normalizasyonu) hafızadan değil **kurulu sürümde koşan testlerle** kanıtlanmıştır; geliştirme sırasında WrapValidator imza hatası gerçek çalıştırmada yakalanıp düzeltildi (models/base.py `_utc_or_none(value, handler)`).

## 10. Sınırlamalar ve bilinen riskler

1. **Minimal yürütücü:** `execute_plan` tüm modlarda tek tamamlama çağrısı yapar. Derin araştırmanın çok turlu/paralel akışı A4–A6, graph yürütmesi ve checkpoint yaşam döngüsü A2 kapsamındadır; A1'deki "rapor" tek geçişlik taslaktır ve gerçek sağlayıcı başarısı sayılmaz.
2. **Somut sağlayıcı adaptörü yok:** `resolve_*_provider` yalnız `test` sağlayıcısını kurar (test ortamında); ollama/openai/anthropic bilinen ad olarak alan doğrulaması yapar ama adaptörleri sonraki fazlara bağlıdır (A0 §10.3 açık kararı).
3. **`article_revision` mekanizması:** A1 alanı **tip olarak** tanımlar (W0 Ç5); backend'in revizyonu nasıl üreteceği B3 öncesi açık karardır — bugünkü `BlogPost.Version` (xmin) bu anlamda kullanılamaz (A0 §7.1).
4. **`ProfileRepository`/`ProjectRepository` portları boş:** arkasında veri kaynağı yok (A0 §3); port sözleşmesi sabitlendi, doldurma açık soru 2'ye (W0 §6) bağlı.
5. **Router sezgisi:** `auto` kararını deterministik anahtar-sözcük/uzunluk sezgisiyle verir; model destekli/rich routing A2 graph'ının işidir — A1 bu sezgiyi yalnız giriş noktası router'ı olarak kullanır.
6. **ProgressKind enum'u kapalıdır** (11 değer); A2+ fazlarında yeni olay türü gerekiyorsa enum genişletilmelidir — bilinçli sıkılık (hatalı veri reddi kabul ölçütü).
7. **`source_scope` enum'u** yorumlamayla belirlendi (plan alanı örneklemiyor); B1 payload eşlemesinde gözden geçirilmeli.
8. Paket henüz `pip install` ile kurulmadı; testler `pythonpath=["app"]` ile koşar. Paketleme doğrulaması (build) bu fazın istenen kontrolü değildi, çalıştırılmadı.

## 11. Sonraki aşamaya aktarılanlar

- A2: `BudgetStore` rezervasyon deseni bu fazda kurgulanmıştır (reserve→commit/release); graph state, node hata türleri ve iptal noktaları buna bağlanabilir.
- B1: 13 modelin JSON alan adları bu paketin `model_dump_json` çıktısıyla birebir eşleşir; `docs/ai-agent-plan/contracts/` şemaları bu çıktıdan türetilebilir. Hata kodları `AgentErrorCode` değerleri olarak taşınır (W0 §1.5).
- A3: `ArticleChunk` ofset sözleşmesi (markdown kaynağına göre) hazır; kod-fence korumalı bölümleme bu modele dolacak.
