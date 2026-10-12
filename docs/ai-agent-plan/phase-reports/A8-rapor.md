# A8 Faz Raporu — Checkpoint ve kesinti sonrası devam davranışı

Tarih: 2026-10-12 · Faz: A8 (W5) · Branch: `feature/ai-agent-integration`
Sorumlu: A8 implementasyon agent'ı (checkpoint/resume)
Plan kaynağı: `docs/ai-agent-plan/01-agent-gelistirme-plani.md` "Aşama A8" (satır 385–411), plan metni asıl alınmıştır.

## 1. Ortam ve ön koşul doğrulaması

- RAG aracı faz başında doğrulandı: `node docs/ai-agent-plan/source/tools/search.cjs verify` → `"valid": true, "sources": 30, "chunks": 60, "stages": 23` (L008 kontrolü).
- A8 CONTEXT'i alındı: `search.cjs search --stage A8 --query "Checkpoint resume interrupt ve iptal sonrası devam" --format prompt` → [LG-PERSISTENCE#C1] (checkpointer/thread_id ayrımı), [LG-PERSISTENCE#C2] (bellek içi saver süreç restart'ında kaybeder; kalıcı arkayol gerekir), [LG-INTERRUPTS#C1/#C2] (kararlı thread kimliği; devam ettirilen node baştan çalışır → yan etkiler idempotent tasarlanmalı), [PY-ASYNCIO#C2] (iptal istisnası bastırılmaz).
- Okunan plan/karar dosyaları: main-prompt.md, decisions.md (D001–D015), progress.md, lessons-learned.md (L001–L009), plan A8 bölümü.

## 2. Gerçekleştirim kararı: dosya tabanlı checkpoint (kapsam kontrolü gerekçesi)

`CheckpointStore` bu fazda **dosya tabanlı dev gerçekleştirimi** ile port arkasına alındı (`FileCheckpointStore`, çalışma dizini altında atomik yazım). **DB-backed checkpoint bilinçli olarak KURULMADI.** Gerekçe: agent tablolarının tek sahibi Python ve Alembic zinciri 0001–0002'de kilitli (D011/D014); paralel B8'in backend migration'ı (`AddContentRevision`, çalışma ağacında mevcut) ve B6'nın iş şeması migration'ıyla çakışma riski taşımak istenmedi. Checkpoint kalıcılığı B6 iş şemasından ayrık tutuldu; DB/Redis arkayolu aynı portu doldurarak sonradan eklenebilir (port sözleşmesi değişmez).

## 3. Oluşturulan yapı

| Dosya | İçerik |
| --- | --- |
| `app/agent_core/checkpoint/__init__.py` | Paket dışa aktarımları; sorumluluk ayrımı docstring'i |
| `app/agent_core/checkpoint/models.py` | `CHECKPOINT_SCHEMA_VERSION=1`, `CheckpointEnvelope` (sürümlü zarf: run + `execution_id` + kind + state şema sürümü + revizyon bağlamı + base64 payload), `ExecutionId` kalıbı, `validate_execution_id`, `new_execution_id`, `ResumeScope` (`full_reuse`/`evidence_stale`/`not_resumable`), `ResumeEvaluation`, `ResumePartition` |
| `app/agent_core/checkpoint/store.py` | `FileCheckpointStore`: tmp + `os.replace` atomik yazım, manifest'li yazım sırası, run başına tek-yazar kilidi, güvenli kimlik zorlaması (yol geçişi reddi), `DEFAULT_CHECKPOINT_DIR=".agent_checkpoints"` |
| `app/agent_core/checkpoint/resume.py` | `save_checkpoint` (zarflı yazım; uyumsuz state şeması yazılmaz), `load_resume_payload` (zarf sürüm/run/yürütme kimliği denetimi; zarfsız A1 payload'ı geçiş), `evaluate_resume` (revizyon kapsamı), `partition_for_resume` (yeniden kullanım/bayat/model-adımı ayrımı) |
| `tests/checkpoint/` | `__init__.py`'li paket (L005); 37 test, kendi conftest'i |
| `app/agent_core/ports/checkpoint.py` | **Additive genişletme (yalnız docstring)**: kalıcılık zorunluluğu, eşzamanlı yazımın desteklenmediği açık sözleşme, yürütme kimliği bağlaması. Yöntem kümesi DEĞİŞMEDİ (`FakeCheckpointStore` yapısal uyumu korunur — `tests/test_adapters_separation.py:50` yeşil) |
| `app/agent_core/entrypoints.py` | Resume entegrasyonu — imza kırılmadı (§5) |

## 4. Plan A8 yapılacakların karşılıkları

| Plan maddesi | Karşılık |
| --- | --- |
| State'i CheckpointStore üzerinden kalıcı saklama | `FileCheckpointStore` (tmp+replace atomik, fsync'li); süreç restart benzetimi testte kanıtlı (`test_persistence_survives_store_reopen`) — bellek içi saver'ın aksine [LG-PERSISTENCE#C2] |
| Kararlı yürütme kimliğiyle checkpoint bağlama; dış adaptör doğrular | `execution_id` kalıbı + `validate_execution_id` (adaptörün doğrulama noktası) + `new_execution_id`; hazırlıkta `PreparedRun.execution_id`'ye bağlanır, zarf ve resume denetler. İstemci yetki kaynağı değildir (A0 §7.4 ilkesi) |
| Eşzamanlı yazımın desteklenmediğinin açık sözleşmesi | `ports/checkpoint.py` + `store.py` docstring sözleşmesi; ikinci eşzamanlı `save` `PortError(validation_error)` ile reddedilir (`test_concurrent_write_to_same_run_rejected`). Algılama kapsamı depo örneği içidir; süreçler arası tek yazarlık B6 worker lease'inin işidir — sözleşmede açıkça yazılıdır |
| Tamamlanan kaynak/araç sonuçlarını yeniden kullanma | `ResumePartition.reusable_evidence_ids/reusable_finding_ids`; kesinti sonrası checkpoint'te toplanan bulgular yeniden kullanılabilir kanıtlandı (§7 graph senaryosu) |
| Yeni model çağrısı gerektiren adımların önceki sonuçlardan ayrımı | `ResumePartition.model_steps` (deep → `["finalize"]`, aksi `["respond"]`) + `pending_subtasks`; kullanım ayrımı testleri |
| İptal ve deadline'ın devam ettirilen çalışmada da uygulanması | `resume`: iptal sinyali aynen geçirilir (`test_resume_cancel_enforced_in_resumed_run`); `ResumeRequest.deadline_seconds` → `_DeadlineBoundedModel` çağrıyı kalan süreyle yarıştırır, aşım `timeout` terminali üretir, süreç asılı kalmaz [PY-ASYNCIO#C2] (`test_resume_deadline_expires_mid_call`) |
| State ve checkpoint şema sürümleri | `CHECKPOINT_SCHEMA_VERSION=1` (zarf) ayrı, `STATE_SCHEMA_VERSION=1` (state payload — mevcut `state/state.py`) ayrı sorumluluk; ikisi de yüklemede denetlenir |
| Uyumsuz eski checkpoint için anlaşılır sonuç | Gelecek zarf sürümü → `validation_error` "payload=v999, desteklenen=v1…" (`test_future_envelope_version_rejected_with_clear_message`, giriş noktası testi dahil); uyumsuz state şeması hem YAZIMDA (`save_checkpoint`) hem YÜKLEMEDE reddedilir; payload içi oynama `deserialize_state` anlaşılır hatasıyla yakalanır |
| Eylem kimlikleri ve kullanım kayıtlarının idempotentliği | Mevcut `event_id=action_id#attempt` sözleşmesi (state/events.py) resume sınırının iki yanında birleşime tabi tutularak kanıtlandı (`test_usage_records_idempotent_across_reexecution`, graph senaryosunda `merge_usage_events` birleşimi) [LG-INTERRUPTS#C2] |
| İçerik revizyonu değişirse sürdürme kapsamı değerlendirmesi | `evaluate_resume`: aynı revizyon → `FULL_REUSE`; ilerleme → `EVIDENCE_STALE` (rota ve makaleden bağımsız sonuçlar sürer, makale kanıtı/bulgusu bayat sayılıp alt sorular yeniden kuyruğa girer); kaldırma/gerileme/başka makale → `NOT_RESUMABLE` (D008 monoton revizyon) |

## 5. Giriş noktası entegrasyonu (ortak dosya, imza kırılmadan)

`entrypoints.py` değişiklikleri — mevcut çağrı biçimlerinin tamamı korunur (tam regresyon kanıtı §6):

- `PreparedRun.execution_id: str | None = None` (additive alan); `prepare_and_route(..., execution_id=None)` (additive kwarg) — verilmezse üretilir, verilirse biçimi doğrulanır.
- `ResumeRequest` additive alanları: `execution_id` (bağlama denetimi), `deadline_seconds` (devam ettirilen çalışmanın süre sınırı), `current_context` (revizyon kapsamı değerlendirmesi).
- `resume`: yükleme `checkpoint.load_resume_payload` üzerinden (zarf sözleşmeleri + A1 dönemi ham payload'a geriye dönük uyumluluk — `test_resume_legacy_raw_payload_still_loads`); `current_context` verildiyse `verify_snapshot_binding` + `evaluate_resume`; `NOT_RESUMABLE` → `stale_snapshot` hatası, `EVIDENCE_STALE` → çalışma GÜNCEL bağlamla sürer ve RUN_RESUMED ilerleme olayında kapsam bildirilir; `deadline_seconds` → `_DeadlineBoundedModel` sarmalayıcısı.
- `prepare_and_route`'ın ham `prepared:run` yazımı KORUNDU: zarfsız payload'a bağlı mevcut testler (`tests/test_entrypoints.py`, `tests/routing/test_router_model.py`) ve A1 davranışı değişmedi; zarflı bağlama `checkpoint.save_checkpoint` API'siyle sunuldu (B6 worker bunu kullanır).

## 6. Doğrulama (gerçek koşumlar)

Komutlar depo kökünden, sırayla:

```
python -m pytest src/services/ai-agent-service/tests/checkpoint -q
→ 37 passed in 0.85s

python -m pytest src/services/ai-agent-service/tests -q \
  --ignore=src/services/ai-agent-service/tests/messaging_broker \
  --ignore=src/services/ai-agent-service/tests/intake \
  --ignore=src/services/ai-agent-service/tests/events \
  --ignore=src/services/ai-agent-service/tests/worker \
  --ignore=src/services/ai-agent-service/tests/control \
  --ignore=src/services/ai-agent-service/tests/content_sync
→ 553 passed, 1 skipped in 9.22s
```

- Faz kapısı 37 test: 13 dosya deposu (kalıcılık/yeniden açma/güvenli kimlik — 6 parametreli/eşzamanlılık sözleşmesi), 8 zarf-şema (yürütme kimliği, gelecek zarf sürümü, state şema reddi yazım+yükleme, legacy geçiş, bozuk gövde), 7 resume semantiği (zarflı/yürütme kimliği uyumsuzluğu/legacy/deadline/iptal), 8 revizyon kapsamı (FULL_REUSE/EVIDENCE_STALE/kaldırma/gerileme/başka makale/güncel bağlamla devam/kullanım idempotentliği/ayrım-stabilitesi), 1 graph ölçekli kesinti senaryosu.
- Tam regresyonda A1 dönemi davranışlar yeşil: `tests/test_entrypoints.py` (resume not_found/bozuk payload/yabancı run), `tests/state/test_graph_runner.py`, `tests/routing` — imza kırılması yok.
- Broker testleri bu fazın kapısında DEĞİL (dispatch kuralı); koşulmadı. `tests/worker`, `tests/control`, `tests/content_sync` dizinleri çalışma ağacında yok — ignore listesi zararsız.

## 7. Kabul ölçütleri senaryoları (plan metni) → kanıt

| Senaryo | Test |
| --- | --- |
| Kaynak toplama sonrasında kesinti → checkpoint'ten devam | `tests/checkpoint/test_interruption_after_collection.py::test_interrupted_after_collection_persists_reusable_results` — gerçek langgraph kurulumu, 2 alt görevin toplama çağrıları tamamlandıktan sonra rapor öncesi iptal; checkpoint (YENİ depo örneğiyle = süreç restart benzetimi) bulgu/kanıt/terminal durumu içerir; `partition_for_resume` 2 yeniden kullanılabilir bulgu + `model_steps=["finalize"]` ayrımı verir; kullanım olayları birleşimde çift sayılmaz |
| Checkpoint'ten devam | `test_resume_with_envelope_and_matching_execution_id_completes` (+ mevcut A1 resume testleri regresyonda yeşil) |
| İptal sonrası devam talebi | İptal edilmiş çalışmanın checkpoint'i saklanır (graph senaryosu: CANCELLED terminali state checkpoint'e yazılır, `restored["outcome"].status is CANCELLED`); devam talebinde iptal sinyali yeniden uygulanır (`test_resume_cancel_enforced_in_resumed_run`) ve kesintisiz devam zarf/yürütme kimliği sözleşmeleriyle sürer |
| İçerik kaldırılması | `test_removed_content_not_resumable` — güncel bağlamda makale referansı yok → `NOT_RESUMABLE`, giriş noktası `stale_snapshot` ile reddeder, model çağrılmaz |
| Eski state şeması | `test_state_schema_rejects_tampered_version_in_payload` (payload içi sürüm oynaması → anlaşılır hata), `test_state_schema_version_mismatch_rejected_on_load` (zarf alanı), `test_save_checkpoint_refuses_unsupported_state_schema` (uyumsuz şema YAZILMAZ) |

## 8. Kullanılan kaynak kimlikleri (RAG — SADECE CONTEXT)

[LG-PERSISTENCE#C1] (checkpointer/store sorumluluk ayrımı — checkpoint paketinin katman ayrımı gerekçesi), [LG-PERSISTENCE#C2] (kalıcı saver zorunluluğu — FileCheckpointStore gerekçesi ve `test_persistence_survives_store_reopen`), [LG-INTERRUPTS#C1] (kararlı thread kimliği — run_id/execution_id kararlılığı), [LG-INTERRUPTS#C2] (devam eden node baştan çalışır → eylem kimliği/kullanım idempotentliği testleri), [PY-ASYNCIO#C2] (iptal istisnası bastırılmaz — `_DeadlineBoundedModel` wait_for davranışı).

## 9. Bulgular

- **F1 (düşük, tasarım kararı olarak kayıtlı):** `FileCheckpointStore`'un eşzamanlı-yazım algılaması depo ÖRNEĞİ kapsamındadır; aynı dizini paylaşan iki örnek/iki süreç bu algılamanın dışındadır. Süreçler arası tek yazarlık dış adaptörün (B6 lease/fencing) sorumluluğudur ve sözleşme bunu açıkça böyle tanımlar (store.py modül docstring'i). Kanıt: `test_concurrent_write_to_same_run_rejected`.
- **F2 (düşük, uyumluluk):** A1 dönemi ham `PreparedRun` payload'ları yürütme kimliği TAŞIMAZ; `request.execution_id` verilse bile eski payload için bağlama kanıtlanamaz ve sessizce kabul edilir (geriye dönük uyumluluk kararı). Yeni yazımlar hazırlıktan itibaren kimlikli; sınırlı uyumluluk penceresi B6'da worker yalnız zarflı yazım yaptığı için kapanır. Kanıt: `test_resume_legacy_raw_payload_still_loads`.
- **F3 (bilgi):** Graph runner (`graph/runner.py` — bu fazın dosya sahipliği DIŞI) state checkpoint'ini terminal yollarının hepsinde yazar; süper-adım ortası çökmelerde en iyi bilinen state langgraph checkpointer'ına bağlıdır (`_crash_state`). B6, süper-adım arası checkpoint sıklaştırmasını kendi kapsamında değerlendirebilir.
- **F4 (takip, orchestrator'a):** Dev deponun varsayılan kökü `./.agent_checkpoints` repo `.gitignore`'da DEĞİL (`git check-ignore` boş). `.gitignore` dosya sahipliğimde olmadığından eklenmedi; depo köküne tek satır `/.agent_checkpoints/` eklenmesi orchestrator takibidir. Testler yalnız `tmp_path` kullandığından çalışma ağacında bu dizin OLUŞMADI (`git status` temiz).

## 10. Sınırlar ve kapsam dışı bırakılanlar

- İş kuyruğu, worker lease, broker recovery: B6/B7 (plan A8: "İş kuyruğu, worker lease'i ve broker recovery'sini burada uygulama; bunlar haberleşme planındadır").
- Checkpoint saklamak durmuş süreci yeniden başlatmaz; devam yürütmeyi dış adaptör başlatır (plan A8 son paragraf). Bu faz yalnız depolama + sözleşme + kapsam kararını verir.
- Graph state'i için yürütme-içi resume (toplanan bulgularla rapor adımının doğrudan sürülmesi) B6 worker bağlantısıyla devreye girer; A8 bunun sözleşme/ayrım katmanını (`ResumePartition`) ve doğruluğunu teslim eder.
- Donmuş alanlara dokunulmadı: `src/contracts/**`, `app/messaging/**`, backend Messaging (B1), models/ports imzaları (yalnız docstring + additive), `web/research/qa/analysis` modülleri. Paralel B8'in backend dosyalarına dokunulmadı (çalışma ağacında gözlemlendi, rapora yansıtıldı).
- DB-backed checkpoint: bu fazda kurulmadı (§2 gerekçe). Alembic zinciri 0001–0002'de değişmedi.

## 11. Ortam olayları

- Paylaşılan checkout'ta paralel B8 (içerik senkronu) agent'ının dosyaları çalışma pencresi içinde göründü: `src/backend/**` değişiklik/migration'ları ve faz sonu itibarıyla `app/messaging/__init__.py` (M) + `app/messaging/content.py` (yeni). A8 bu dosyalara DOKUNMADI; dosya sahipliği ayrımı korundu (L006 bağlam kaydı).
- `git checkout/switch/stash` kullanılmadı (L006); `nul` dosyası üretilmedi (L002); commit/push yapılmadı (orchestrator'a ait).

## 12. Sonuç

A8 plan listesindeki dokuz madde gerçek implementasyonla tamamlandı; beş kabul senaryosu testle kanıtlandı. Faz kapıları: `tests/checkpoint` 37 passed; tam regresyon 553 passed/1 skipped. Durum: **doğrulanmayı bekliyor** (orchestrator bağımsız incelemesi).
