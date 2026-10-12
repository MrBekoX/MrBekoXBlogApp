# A2 Faz Raporu — LangGraph state ve bütçe politikası

- **Faz:** A2 (ortak state, reducer'lar, paralel birleştirme, checkpoint-dışı artifact deposu, atomik bütçe rezervasyonu, sınırlı retry, iptal/deadline)
- **Tarih:** 2026-10-11
- **Branch / temel:** `feature/ai-agent-integration`, başlangıç HEAD `e17095b`; çalışma sırasında orchestrator `main`'e checkout yapıp `d72a607`'i commit'leyip geri döndüğü için doğrulama HEAD'i `6ed4cc7` (A1/B1 ancestry'si korundu: `b232966` → `4a887cb` → `7344fa6` → `e17095b` → `6ed4cc7`)
- **Rol:** A2 implementasyon agent'ı (LangGraph state ve bütçe politikası)
- **Ön koşul girdileri:** `docs/ai-agent-plan/01-agent-gelistirme-plani.md` Aşama A2, `agent-architecture.md`, `phase-reports/A0-rapor.md`, `phase-reports/W0-ortak-mimari-kararlari.md`, A1 kodu (`app/agent_core` models/ports/entrypoints), decisions.md D001–D012, lessons-learned L001–L004
- **Yazılan dosyalar (izinli kapsam):** `app/agent_core/state/**`, `app/agent_core/budget/**`, `app/agent_core/graph/**` (yeni), `tests/state/**` (test sahipliği), `app/agent_core/ports/budget.py` (yalnız additive enum üyesi) ve `pyproject.toml` (yalnız `langgraph` bağımlılık satırı) — son ikisi görevin "yalnız senin" kapsamında. `entrypoints.py`, `models/`, `routing.py`, `src/contracts/**`, messaging/content dosyalarına dokunulmadı. Commit/push yapılmadı.
- **Kapsam dışı bırakılanlar:** gerçek retrieval/içerik (A3), gerçek model/web sağlayıcı adaptörleri (A4/A6), gerçek rapor dili ve tur kararları (A7), kalıcı checkpoint arka yolu ve resume akışı (A8), broker (B2).

## 1. Ortam ve ön koşul doğrulaması

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| langgraph sürümü | `python -c "import importlib.metadata as m; print(m.version('langgraph'), m.version('langgraph-checkpoint'))"` | langgraph **1.0.6**, langgraph-checkpoint **4.0.0** (global kurulu, .venv kurulmadı) |
| pydantic / pytest | `python -c "import pydantic, pytest; …"` | pydantic 2.11.7, pytest 8.3.3 |
| A2 RAG CONTEXT | `node docs/ai-agent-plan/source/tools/search.cjs search --stage A2 --query "LangGraph state checkpoint paralel görev ve iptal" --format prompt` (+ reducer sorgusu) | CONTEXT geldi: [LG-WORKFLOWS#C1], [LG-WORKFLOWS#C2], [LG-PERSISTENCE#C1], [LG-PERSISTENCE#C2], [LG-STREAMING#C1], [PY-ASYNCIO#C1], [PY-ASYNCIO#C2]. Reducer API imzası arşivde YOKTU; doğrudan kurulu paketle probe yapıldı (aşağıda) |
| Kurulu API probe | python ile `StateGraph` + `Annotated` reducer + `Send` fan-out + `MemorySaver` koşusu | Fan-out/reducer/MemorySaver davranışı doğrulandı; **pydantic modelleri hash'lenemediği için dedupe reducer'ı nesne hash'iyle DEĞİL id alanıyla yazılmalı** (probe `TypeError: unhashable type: 'P'` üretti; tasarım buna göre kuruldu) |

## 2. Eklenen modül yapısı

```
app/agent_core/
├── state/                        # ORTAK STATE (plan A2 alan kümesi)
│   ├── state.py                  # AgentState TypedDict + reducer'lar + serialize/deserialize + STATE_SCHEMA_VERSION=1
│   ├── events.py                 # UsageEvent (estimated/uncertain işaretli), NodeErrorRecord, usage_record_from_events
│   └── artifacts.py              # ArtifactRef (içerik adresli) + ArtifactStore portu + InMemoryArtifactStore
├── budget/
│   ├── policy.py                 # BudgetPolicy (plan başlangıç sınırları, from_budget_profile) + Deadline (monotonik saat)
│   ├── store.py                  # PolicyBudgetStore: BudgetStore portunun atomik politika uygulaması
│   └── guard.py                  # BudgetGuard: rezervasyon → çağrı → kullanım olayı → sınırlı retry → belirsiz kullanım
└── graph/
    ├── nodes.py                  # Node sözleşmeleri (prepare/plan/subtask/collect/finalize/respond) + ResearchEffects protokolü + TaskContext
    └── runner.py                 # build_research_graph (StateGraph + Send fan-out) + run_agent_graph + terminal eşleme
tests/state/                      # 5 test modülü + effects.py (deterministik etkiler; conftest YOK — §6'ya bak)
```

State alanları planın listesinin birebir karşılığıdır: `messages` (konuşma mesajları), `route` (router kararı), `article_revision` (içerik revizyonu), `plan`, `evidence` (kanıtlar), `findings` (ara bulgular), `usage_events` (kullanım görünümünün kaynağı), `outcome` (sonuç); ek olarak `errors` (node hata izleri), `artifact_refs` (checkpoint-dışı referanslar), `pending_subtasks`/`research_round` (paralel tur kurgusu), `schema_version`/`run_id`/`context`.

## 3. Reducer'lar ve paralel birleştirme

| Kanal | Reducer | Sözleşme |
| --- | --- | --- |
| `evidence` | `merge_by_id("evidence_id")` | Paralel `Send` worker sonuçları benzersiz kimlikle birleşir; **ilk gelen kazanır**, aynı kimlik kopyası eklenmez → tekrar yürütmede kanıt çoğalmaz |
| `findings` | `merge_by_id("finding_id")` | `finding_id` worker girdisiyle kararlıdır (`find-{sub_index}`) |
| `usage_events` | `merge_by_id("event_id")` | `event_id = action_id#attempt`: aynı eylemin yeniden yürütümü aynı kimliği üretir → kopya kullanım kaydı oluşmaz; retry aynı `action_id` ile yeni `attempt` açar → ayrı deneme olarak bütçeye yazılır |
| `messages` | `merge_messages` | `(role, content, created_at)` kimliğiyle birebir kopya düşürür |
| `artifact_refs` | `merge_by_id("artifact_id")` | `artifact_id` içerik adreslidir (`sha256:{digest[:32]}`) → aynı sayfanın tekrar okunması tek referans üretir |
| `errors` | `merge_by_id("error_id")` | Node/bütçe hata izleri |
| `route`/`plan`/`outcome`/`pending_subtasks` | LangGraph varsayılanı (son yazan kazanır) | Yalnız tek node yazar; paralel yazım yok |

Büyük kaynak metinleri state'e girmez: `InMemoryArtifactStore.put()` metni depolar, state yalnız `ArtifactRef` (byte_size + sha256) taşır. Test bunu payload üstünden kanıtlar (`test_large_source_text_stays_out_of_checkpoint`: 8 KB'lık sayfa metni checkpoint baytlarında yok; referans depodan geri çözülür).

## 4. Bütçe politikası ve atomik rezervasyon

- **BudgetPolicy** (yapılandırılabilir; parantez içi plan önerisi): `max_sub_questions`(4), `max_search_calls`(8), `max_source_pages`(12), `max_research_rounds`(2, ilk tur dahil), `max_parallel_subtasks`(3), `max_total_tokens`(200k), `max_tool_attempts`(24), `max_model_calls`(16), `max_duration_seconds`(300), `max_attempts_per_action`(2 — sınırlı retry). `from_budget_profile`, ExecutionContext'in sunucu onaylı `BudgetProfile` sınırlarını politika üst sınırı olarak bindirir (W0 §6.5); araştırma sınırları profil taşımaz.
- **PolicyBudgetStore** (BudgetStore portunun uygulaması): sınır denetimi `committed + reserved + istenen ≤ kapasite` şeklindedir ve `threading.Lock` altında kesintiye uğramayan tek kritik bölümde yapılır → aynı event loop'taki paralel `Send` worker'ları ortak bütçeyi aşamaz (kabul ölçütü 1). Kanıt: `test_parallel_reserves_cannot_oversubscribe_capacity` — kapasite 8 iken 40 eşzamanlı `reserve` isteğinin tam 8'i geçer, 32'si çağrı başlamadan `budget_exhausted` ile reddedilir.
- **BudgetKind uzantısı (additive):** `SOURCE_PAGE_READ` ve `RESEARCH_ROUND` üyeleri eklendi (plan: "araştırma turu sınırlarını BudgetStore üzerinden denetle"). Mevcut üye değerleri değişmedi; A1 testlerinin tamamı yeşil (§7).
- **BudgetGuard.guarded akışı:** (1) `assert_active` (deadline→timeout, cancel→cancelled; çağrı öncesi, dış etki yok), (2) çağrı rezervasyonu (MODEL_CALL'da ek olarak token bütçesinin çağrı-başına dilimi), (3) çağrı, (4) kullanım olayı. Hata yolları: `budget_exhausted` → çağrı başlamaz, rezervasyon release; `retryable` arıza → çağrı rezervasyonu commit (**başarısız deneme ve retry bütçeye dahil**), token rezervasyonu release, `outcome="failed"` olayı, politika sınırı + kalan süre (>50 ms) dahilinde tekrar; `CANCELLED`/`asyncio.CancelledError` → dış çağrının gerçekleşip gerçekleşmediği bilinmediğinden **`uncertain=True, estimated=True` olayı** yazılır, rezervasyonlar ihtiyatla commit edilir ve istisna bastırılmadan yükselir [PY-ASYNCIO#C2]. Sağlayıcı kullanım bilgisi yoksa/0 ise token `estimate_tokens` (4 kar/token) ile tahmin edilir ve olay `estimated=True` işaretlenir.
- **Deadline**: monotonik saat; node girişi + her guard denemesi + worker'ın çağrı sonrası sınırında denetlenir.

## 5. Graph yürütücü ve terminal eşleme

Graph şekli planın "Derin araştırma mimarisi" diyagramıdır: `START → prepare → (koşul) plan | respond`; `plan → [Send×≤3 subtask] → collect → (koşul: bütçe+tur+eksik bulgu varsa tekrar fan-out) → finalize → END`. Fast/analysis doğrudan `respond`'a gider (test: plan node'u hiç çalışmaz).

Node sorumlulukları ve hata türleri `graph/nodes.py` modül docstring'inde tablo halinde tanımlıdır. Runner'ın terminal eşlemesi: `CANCELLED` → `cancelled`; `budget_exhausted`/`timeout` + mevcut bulgu → **mekanik kısmi raporla `partial`** (yalnız tamamlanmış bulguların özeti; gerçek rapor dili A7'nindir), bulgu yok → `failed(error_code)`; `stale_snapshot`/`validation_error`/`config_error` → `failed`. Çökme yolunda checkpointer varsa son superstep state'i best-effort okunur (`_crash_state`); tam kurtarma A8 konusudur. Terminal hata izi `errors` kanalına `NodeErrorRecord` olarak yazılır ve checkpoint'e girer.

Etkiler (`ResearchEffects`) enjekte edilir: A2 yalnız sözleşme + mekaniği sağlar, gerçek plan/araştırma/rapor davranışı A4–A7'nindir. `TaskContext.guarded` dış çağrıları bütçe/iptal sınırına sokar ve olayları `events_sink` ile **istisna yollarında da** toplar.

## 6. Ortam olayı: aynı çalışma ağacında yabancı git işlemi (L002 tipi ortam tuzası)

Çalışma sırasında başka bir süreç aynı checkout'ta `main`'e geçip `d72a607` ("chore: ignore local zcode…") commit'ledi ve feature branch'e döndü (reflog kanıtı: `git reflog` → `checkout: moving from feature/ai-agent-integration to main` → `commit d72a607` → `checkout: moving from main to feature/ai-agent-integration`). Bu pencerede iki Edit çağrım "File does not exist" ile reddedildi ve `untracked` dosyalarım geçici olarak görünmez oldu (muhtemel `git stash -u`/pop döngüsü; ignore'lu `__pycache__` yerinde kaldı). Dosyalar zedelenmeden geri geldi; iki edit yeniden uygulandı. **Önlem önerisi:** paralel faz agent'ları aynı working tree'yi paylaşırken orchestrator branch/checkout işlemlerini fazların yazma pencereleriyle çakıştırmasın.

Ayrıca bu olayın ayırd edilmesine yarayan kendi hatam şuydu: `tests/state/conftest.py` açtığımda pytest prepend modunda bu dosya `conftest` modül adını ele geçirip kök `tests/conftest.py`'yi gölgeliyor, A1 testleri (`import conftest` yapan `test_models_validation/entrypoints/serialization`) tam suite koşusunda `AttributeError: module 'conftest' has no attribute 'make_context'` ile 61 test kırmıştı. Çözüm: conftest'i silip yardımcıları `tests/state/effects.py` modülüne taşıdım (testler `import effects`). Ders: alt dizin test paketlerinde `conftest.py` ancak dizin `__init__.py`'li paketse güvenlidir (bkz. `tests/messaging_broker/__init__.py`); aksi halde yardımcılar ayrı adlandırılmış modüle konmalıdır.

## 7. Gerçek test çıktıları

| Kapı | Komut | Sonuç |
| --- | --- | --- |
| **A2 gate (görevin adıyla)** | `python -m pytest src/services/ai-agent-service/tests/state -q` | **34 passed** |
| Tam servis suite'i (A1+B1+A2+A3/B2 paralel işleri dahil) | `python -m pytest src/services/ai-agent-service/tests -q` | **277 passed, 1 skipped** (A1'in 171+1 baseline'ı korundu; BudgetKind uzantısı kırmadı) |
| A1 dosyaları izole | `python -m pytest tests/test_models_validation.py tests/test_entrypoints.py tests/test_adapters_separation.py tests/test_provider_config.py tests/test_models_serialization.py -q` | 74 passed |
| Derleme | `python -c "compileall.compile_dir('app/agent_core', force=True)"` | tüm modüller derlenir |

A2 testlerinin kabul ölçütü karşılama haritası (plan A2:222-227):

| Kabul ölçütü | Kanıt test |
| --- | --- |
| Paralel görevlerle bütçe sınırı aşılamıyor | `test_parallel_reserves_cannot_oversubscribe_capacity` (40 gather / kapasite 8 → 8+32), `test_budget_exhaustion_in_parallel_subtasks_ends_partial` |
| İptal edilmiş çalışma yeni araç çağrısı başlatmıyor | `test_cancelled_run_starts_no_new_tool_calls` (`started_calls == []`), `test_cancel_mid_subtask_blocks_following_calls` (ilk çağrıdan sonrası başlamaz) |
| State checkpoint'e yazılıp geri yüklenebiliyor | `test_state_roundtrip_through_checkpoint_store`, `test_state_checkpoint_roundtrip_after_run` (CheckPointStore portu), `test_langgraph_checkpointer_persists_superstep_state` (MemorySaver + `compiled.get_state`) |
| Kullanım kayıtları tekrar yürütmede kopya oluşturmuyor | `test_usage_events_deduplicated_on_reexecution`, `test_reexecution_of_same_actions_yields_no_duplicate_usage` (iki tam yürütümün olay birleşimi tek yürütümle eşit) |
| Büyük metinler checkpoint dışında | `test_large_source_text_stays_out_of_checkpoint` |
| Retry/tahmin/belirsiz kullanım | `test_retryable_failure_retries_within_policy_and_consumes_budget`, `test_provider_usage_missing_is_marked_estimated`, `test_cancellation_during_call_records_uncertain_usage`, `test_uncertain_event_reaches_sink_and_is_not_counted_as_call` |
| Sınır kümesi (4/8/12/2/3 + token/araç/süre) | `test_policy_caps_cover_every_budget_kind`, `test_policy_from_budget_profile_tightens_defaults`, `test_deep_research_completes_within_policy_limits`, `test_deadline_exceeded_ends_terminal` |

Not: Testler gerçek langgraph 1.0.6 kurulumuyla koşar; etkiler deterministik double'dır — başarılar gerçek model/web sağlayıcı başarısı değildir (fixture/test-double sınırı, ana prompt kuralı).

## 8. Kullanılan kaynak kimlikleri (yalnız gerçekten gelen CONTEXT parçaları)

- [LG-WORKFLOWS#C1] — yönlendirme/koşullu geçişler node sınırlarının kurulması
- [LG-WORKFLOWS#C2] — orchestrator-worker; Send ile paralel girdi; **paralel sonuçların ortak state'e birleşiminin açık tanımlanması** (reducer sözleşmelerinin gerekçesi)
- [LG-PERSISTENCE#C1] — checkpointer (thread state snapshot) ↔ store (iş verisi) ayrımı; artifact deposunun checkpoint'ten ayrı gerekçesi
- [LG-PERSISTENCE#C2] — bellek içi saver'ın süreç yeniden başlangıcında kaybı; kalıcı arka yol A8'de
- [LG-STREAMING#C1] — progress yayınının custom stream'e taşınabileceği (A2'de kullanılmadı; DomainProgress/ProgressSink sözleşmesi korundu)
- [PY-ASYNCIO#C1] — yapılandırılmış eşzamanlılık: worker yaşam döngüsü superstep kapsamında
- [PY-ASYNCIO#C2] — iptal istisnası bastırılmaz, cleanup sonrası yükselir (guard'ın belirsiz kullanım + re-raise akışı)

Arşivde reducer API imzası bulunmadığından LangGraph'a özgü davranış (Send, reducer çağrım şekli, MemorySaver) **kurulu 1.0.6 paketi üzerinde koşulan probe ve testlerle** doğrulandı; hafızadan API iddiası yazılmadı.

## 9. Sınırlamalar ve sonraki aşamaya aktarılanlar

1. **InMemoryArtifactStore / PolicyBudgetStore süreç içidir.** Dağıtık/çok süreçli üretim için atomik arka yol (Redis/PG) A8'de aynı portların arkasına eklenmelidir; reserve/commit/release sözleşmesi buna hazırdır.
2. **Mekanik kısmi rapor** (bütçe bitişinde bulgu özeti) yer tutucudur; gerçek rapor kompozisyonu ve tur kararı A7'dedir.
3. **MODEL_CALL token rezervasyonu** çağrı başına dilimdir (`max_total_tokens // max_model_calls`); dilim aşımı commit ile kaydedilir, birikimli aşım sonraki reddetmelerle görünür. Gerçek sağlayıcı kullanım verisi gelince (A4+) tahmin oranı kalibre edilmelidir.
4. **Checkpoint payload şeması** `STATE_SCHEMA_VERSION=1`; uyumsuz sürüm `validation_error` ile reddedilir — sürüm geçiş politikası A8 ile gelir.
5. **errors kanalı** collect bütçe reddi + runner terminal iziyle sınırlıdır; node bazlı ayrıntılı hata günlüğü A8 resume akışıyla zenginleşecektir.
6. A3/B2 paralel işlerinin dosyaları (`agent_core/content/`, `app/messaging/` genişlemesi, docker-compose) bu fazca dokunulmadı ve değerlendirilmedi.
