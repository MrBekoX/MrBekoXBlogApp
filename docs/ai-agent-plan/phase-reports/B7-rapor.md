# B7 Faz Raporu — Retry, DLQ, İptal ve Backpressure

Faz: B7 (W5) · Tarih: 2026-10-12 · Sahip: B7 implementasyon agent'ı
Plan: `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` satır 402-436 ("Aşama B7") satır satır uygulandı.

## 1. Özet

Transport hatası ↔ kalıcı sözleşme hatası ↔ graph yürütme hatası ayrımı, hedefe özel
gecikmeli retry kademeleri (10 sn / 30 sn / 2 dk; son denemede DLQ), confirm-before-ACK
kuralı, DLQ replay yeniden doğrulaması, kabul edilmiş iş backlog'u + en eski iş yaşı
ölçümü, sistem düzeyi kapasite sınırı, backend iptal komutu (.NET CancelAgentRunCommand,
B3 deseni), Python kontrol tüketicisi (agent.control.q), terminal-öncelik kuralları ve
iki taraflı deadline reaper gerçek implementasyon + gerçek broker (RabbitMQ 4.2.9, özel
vhost `blogapp_w5_b7`) + gerçek PostgreSQL (scratch DB `blogdb_agent_b7`) üstünde
doğrulandı.

## 2. Ortak store sözleşmesinin uygulanması

Sözleşmenin B7 tarafı `app/messaging/control_store.py`:

- `record_cancel_intent(run_id, requested_by)` → `agent.cancel_intents` INSERT + outbox
  olayı TEK transaction. İş zaten terminal → `already_terminal` (terminal kazanır); iş
  `queued` → `queued_cancelled` (queued→cancelled + `agent.run.cancelled` olayı aynı
  transaction — execute-öncesi cancel engeli); iş `running` → `recorded` (niyet kaydı
  TERMINAL DEĞİLDİR); iş yok → `recorded` (execute henüz gelmedi: niyet bekler).
- `mark_cancelled_if_running(run_id)` → `status='running' VE cancel intent VAR` koşullu
  ATOMİK UPDATE → cancelled + terminal olay; aksi `untouched`.
- Terminal-öncelik: completed commit'i intent insert'ünden önceyse `already_terminal`;
  intent önceyse B6'nın `complete_job`'u `rejected` döner ve terminal bu tarafta üretilir.

Sözleşmenin B6 tarafı (claim_next_job/renew_lease/complete_job/fail_job) PARALEL B6
sahipliğinde olduğundan **sözleşme metnine göre** `tests/control/doubles.py::
B6WorkerStoreDouble` ile temsil edildi (SKIP LOCKED claim, fencing eşitliği ve aktif
cancel-intent yokluğu guard'lı complete/fail). **GERÇEK B6 store'u ile uçtan uca iptal
yarışı testleri BÜTÜNLEŞTİRME fazında koşulacaktır** (dispatch notu).

## 3. Retry / DLQ (`app/messaging/retry.py`)

- Sınıflandırma: `classify_exception` → `transport` (`TransportError`) | `contract`
  (`AgentContractError`, `ControlPolicyError`, `JobPayloadConflict`, **bilinmeyen tüm
  istisnalar** — kör retry döngüsü kurulmaz) | `graph` (`GraphExecutionError` → ACK;
  kalıcı job politikası B6'nın).
- Kademeler: `RetryTierPolicy` (varsayılan `10/30/120` sn = `DEFAULT_RETRY_TIERS`;
  topology B2'den parametrik). Toplam deneme = kademe+1; son denemede `NACK(requeue=false)`
  → DLQ. Sürekli nack/requeue döngüsü YOK.
- **Confirm-before-ACK**: retry yeniden yayını `BrokerPublisher.publish_raw` (confirm'lu)
  ile AYNI `message_id` + `delivery_attempt+1` (yalnız sayaç güncellenir; `.NET
  WithDeliveryAttempt` karşılığı) yapılır; confirm gelmezse `RetryAction.HOLD` — eski
  teslim ACK/NACK edilmez, broker tekrar teslim eder (plan satır 416).
- `RetryAwareBrokerConsumer`: `BrokerConsumer` alt sınıfı; retry kararını
  ACK/NACK(requeue=false)/HOLD'a çevirir (temel sınıf normal dönüşte ACK attığı için).
- Poison: şema hatalı gövde tek çalıştırmada DLQ'ya düşer (test: `deliveries == 1`).
- `DlqReplayService`: replay öncesi sıralı yeniden doğrulama — zarf sözleşmesi
  (poison → DLQ'da kalır), kimlik (payload_hash uyuşmazlığı → `identity_mismatch`),
  mevcut terminal (`already_terminal` → teslim düşürülür), iptal (intent varsa replay
  yok; running iş `mark_cancelled_if_running` ile terminalleşir), deadline (süresi
  geçmiş iş **körlemesine başlatılmaz**; DLQ'da kalır — DLQ'nun DLX'i olmadığından
  nack mesajı düşürürdü, bilinçli olarak dokunulmaz). Kalan mesaj orijinal exchange'e
  AYNI message_id ile confirm'lu yayınlanır, DLQ teslimi confirm SONRASI ACK'lanır.
- Backpressure: `ControlStore.backpressure()` — accepted_backlog (queued+running),
  en eski aktif iş yaşı + run_id; broker kuyruk derinliğiyle birlikte ölçülür (test
  `test_probe_combines_queue_depths_and_store_snapshot`: broker boşken kalıcı backlog
  görünür — mesaj kaybı olsa bile iş kaybolmaz).

## 4. Kontrol tüketicisi ve reaper (`control.py`, `reaper.py`)

- `ControlConsumerService` (agent.control.q): B1 `parse_envelope` → tür/yön politikası
  (`ControlPolicyError` kalıcı → DLQ) → inbox idempotency (consumer_name="control") →
  cancel: `record_cancel_intent`; resume/action-result: bilinmeyen run → kalıcı ihlal →
  DLQ (sessiz döngü yok), bilinen run → kalıcı kayda alınır ve ACK (graph devam ettirme
  B9 bağlantısı; bu fazda yürütme tetiklenmez — rapor sınırı).
- `DeadlineReaper`: deadline'ı geçmiş aktif işleri kapatır — cancel intent yoksa
  `failed` + `agent.run.failed(error_code=timeout)`, varsa `cancelled` kazanır; her iş
  kendi transaction'ında koşullu UPDATE (worker bu arada terminal yazdıysa olay
  ÜRETİLMEZ). Ayrıca cancel intent'li `queued` işleri başlatılmadan kapatır
  (execute-öncesi engel finalizer'ı). `run_once` + `run_forever`.

## 5. Backend (.NET, B3 deseni — additive)

- `CancelAgentRunCommand` (`Features/AgentFeature/Commands/CancelAgentRunCommand/`):
  oturum doğrulama (JWT/misafir) → sahiplik (OwnerKey) → terminal ise
  `already_terminal` (istek kaydedilmez; geç cancel terminali geri götürmez) → açık
  cancel komutu varsa `replay` (idempotent, çift kayıt yok) → zarf commit ÖNCESİ
  `AgentContractValidator` ile doğrulanır → komut TEK transaction'da outbox'a yazılır.
  Yanıt `requested`: cancel intent kaydı terminal değildir; terminali
  `agent.run.cancelled` projection'ı getirir (B5).
- `AgentControlEnvelopeComposer` (Common/Messaging'e YENİ dosya — B1'in donuk
  dosyalarına dokunulmadı; B5/B8 önceli: AgentContentEventComposer aynı klasörde ayrı
  dosyadır). `ComposeCancellationRequested`: `agent.cancel.requested` zarfı, null
  alan taşınmaz.
- **Backend cancel intent kaydı sapması (raporlanır):** ayrı `agent_cancel_intents`
  tablosu yerine kalıcı niyet kaydı = `OutboxMessage` satırı (RunId + `agent.cancel.requested`
  + Pending). Gerekçe: ayrı tablo EF migration gerektirir; Infrastructure dosya
  sahipliği B7 kapsamı dışındadır. Yeterlilik: idempotency sorgusu ve UI "iptal
  isteniyor" göstergesi bu satırdan türetilebilir; niyetin işletimsel asıl kaydı
  agent tarafındaki `agent.cancel_intents`'tir (kontrol tüketicisi komuttan yazar).
  B11/entegrasyon sahibi isterse ayrı tabloya geçiş additive migration'dır.
- **Sistem düzeyi kapasite sınırı:** `AgentAcceptanceSettings.MaxActiveRunsTotal`
  (varsayılan 100) + `AcceptAgentRunCommandHandler` içinde `MaxActiveRunsPerOwner`
  kontrolünün HEMEN YANINDA toplam aktif iş sayımı; doluysa Domain hatası
  ("Sistem agent kapasitesi dolu…").
- **Backend reaper:** `AgentRunDeadlineReaper` (Application, Features/AgentFeature/
  Services): `Status=Accepted && DeadlineAt<now` → `Failed` + `TerminalAt` +
  `ResultJson={"terminal":"deadline_exceeded","closed_by":"backend-reaper"}`. Agent
  sonradan gerçek terminal olayı getirirse B5 kuralı uygulanır (daha yüksek
  sequence'li terminal yazılabilir) — reaper erken kapatma doğru sonucu engellemez.
  Hosting notu: `AddScoped` + BackgroundService sarmalayıcı Infrastructure DI'sında
  bağlanmalıdır (B7 dosya kapsamı Application ile sınırlı; idempotent koşullu
  güncelleme nedeniyle sık çağrı güvenlidir) → entegrasyon fazı devri.

## 6. Dosyalar (sahiplik)

Yeni (izinli kapsam):
- `src/services/ai-agent-service/app/messaging/retry.py`, `control_store.py`,
  `control.py`, `reaper.py`
- `src/services/ai-agent-service/tests/control/` (`__init__.py`'li paket: conftest,
  doubles, test_retry_policy, test_retry_tiers_broker, test_poison_dlq,
  test_dlq_replay, test_control_cancel, test_reaper, test_backpressure)
- `src/backend/Core/Application/Common/Messaging/AgentControlEnvelopeComposer.cs`
- `src/backend/Core/Application/Features/AgentFeature/Commands/CancelAgentRunCommand/`
  (Request, Handler, Dto)
- `src/backend/Core/Application/Features/AgentFeature/Services/AgentRunDeadlineReaper.cs`
- `src/backend/Presentation/Api.Tests/Messaging/Cancel/` (Fixture, CancelRunCommandTests,
  BackpressureTests)
- Bu rapor.

Değişiklik (additive):
- `app/messaging/__init__.py`: yalnız B7 export eklendi (0 satır silme; B8'in içerik
  exportları korundu — diff doğrulandı).
- `AgentAcceptanceSettings.cs`: `MaxActiveRunsTotal` (+6 satır).
- `AcceptAgentRunCommandHandler.cs`: sistem sınırı kontrolü (+11 satır; sahip limitinin
  yanında, mevcut akış değişmedi).

Dokunulmadı (kapsam dışı): `worker.py`/`job_store.py` (B6 — paralel ajanın ağacındaki
değişiklikleri), `agent_core/**`, sözleşmeler, docker-compose.

## 7. Kabul ölçütleri → test eşlemesi (plan satır 436)

| Ölçüt | Test |
| --- | --- |
| timeout/retry | `test_transport_failures_walk_tier_ladder_then_dlq` (1s/2s/3s gerçek TTL kuyrukları; attempt 0→1→2→3; aynı message_id; DLQ), `test_unconfirmed_republish_holds_delivery` (confirm yok → HOLD, kayıp yok) |
| poison mesaj | `test_schema_invalid_message_goes_to_dlq_once` (deliveries==1, DLQ=1), `test_unparseable_body_is_not_republished`, `test_wrong_type_for_queue_is_permanent_rejection` (iş ÜRETİLMEDİ) |
| DLQ replay | `test_valid_job_is_replayed_to_origin_with_same_id`, `test_expired_job_is_not_blindly_replayed`, `test_cancel_intent_blocks_replay_and_finalizes_running`, `test_terminal_job_replay_is_discarded`, `test_payload_mismatch_is_not_replayed`, `test_unknown_run_is_replayed_to_intake` |
| execute-öncesi cancel engeli | `test_cancel_queued_job_finalizes_before_execution` (queued→cancelled+olay; claim None), `test_cancelled_queued_job_is_finalized_without_execute` (reaper finalizer'ı), store double ile terminal-öncelik iki yön: `test_terminal_precedence_both_directions_with_worker_double` |
| geç terminal geri götürmez | `test_cancel_terminal_job_is_rejected_and_leaves_state` (python), `LateCompletedEvent_AfterCancelled_DoesNotRestoreRun` (.NET projection: cancelled(seq1) sonrası completed(seq1/seq0) → Stale; durum Cancelled kalır) |
| backlog/en eski iş + kapasite | `test_backpressure_snapshot_counts_active_jobs_only`, `test_probe_combines…`, `Accept_WhenSystemCapacityFull_IsRejected` / `Accept_WhenBelowSystemCapacity_IsAccepted` (.NET) |
| reaper | `test_expired_running_job_fails_with_timeout`, `test_expired_job_with_cancel_intent_is_cancelled`, `test_live_job_is_untouched`, `test_worker_terminal_wins_over_reaper`, `Reaper_ClosesExpiredAcceptedRun_AndKeepsLiveRun`, `Reaper_IgnoresTerminalRuns` (.NET) |

## 8. Gerçek test çıktıları (bu ask sırasında koşuldu)

GATE komutları (ask'ın verdiği haliyle):

- `python -m pytest src/services/ai-agent-service/tests/control -q` (repo kökü) →
  **38 passed, 1 warning in 40.91s** (tek uyarı: asyncpg `get_event_loop` deprecation
  notu — B4 conftest'te bilinen/mevcut desen). Servis kökünden geliştirme sırasında
  ayrıca 3 tam paket koşumu: 38 passed.
- `dotnet test src/backend/Presentation/Api.Tests --nologo -v q` (repo kökü) tam suite
  koşumları (seri; L009):
  1. 145/145 **Başarılı** (2 m 48 s) — cleanup uyarısı (aşağıda §10),
  2. 145/145 **Başarılı**,
  3. 144/145 — tek başarısız `ContentSnapshotSyncServiceTests.Sync_Produces…` (B8'in
     yürütmekte olan paralel çalışması; **tek başına yeşil**, tam koşumda koleksiyonlar
     arası broker çakışması — L009 deseni; dosya B7 sahipliği dışında),
  4. **Ortam olayı:** bir koşum penceresinde broker kabı dışarıdan restart edildi
     (docker ps: "Up About a minute"; kullanıcı/orkestratör paralel çalışması — L006);
     aynı penceredeki iki koşum 3 ve 22 başarısızlık gösterdi (L009: broker yokluğu/
     kuyruk sıfırlanması), sonraki koşumda B7 testleri dahil yeşile döndü,
  5. 144/145 — tek başarısız yine B8'in ContentSnapshot testi (2 s'de beklenen 0
     yerine 1: kuyruk kalıntısı; B8 sahipliğinde).
  **B7'nin 13 .NET testi hiçbir koşumda başarısız olmadı** (izole:
  `--filter FullyQualifiedName~Messaging.Cancel` → 13/13, en az 4 koşum).

## 9. Kararlar ve sapmalar

1. Backend cancel intent kaydı = `OutboxMessage` satırı (bkz. §5; Infrastructure
   migration sahipliği kapsam dışı). Bütünleştirme sahibi teyit eder.
2. `AgentControlEnvelopeComposer` Common/Messaging'e yeni dosya (donuk B1 dosyaları
   değişmedi; B5/B8 önceli var).
3. Kontrol komutlarında `requested_by` = zarf `producer` değeri ("backend-net");
   `AgentCancellationRequestedV1` sözleşmesi istek sahibi alanı taşımaz (DONMUŞ).
4. Retry kademeleri üretimde 10/30/120; test vhost'unda topology parametrik olduğu
   için 1/2/3 sn declare edildi (üretim kuyruk adları kademeyi adına gömer; kademe
   değişimi PRECONDITION_FAILED gerektirir — B2 raporunda kayıtlı).
5. `agent.jobs` B6 sözleşme şekli, B7 scratch DB'sinde dispatch DDL'iyle kuruldu
   (`tests/control/conftest.py::B6_CONTRACT_DDL`; alembic 0003 B6'nındır). Sözleşme
   kolonlarına ek `conversation_id`/`correlation_id` bağlam kolonları tutuldu (B4
   intake bunları zaten yazar; terminal olay zarfı bunlara ihtiyaç duyar).
6. DLQ replay operasyonel kimlikle yapılır (testte admin): agent_svc'nin komut
   exchange'ine yazma izni yoktur (D013). Agent rolüne retry exchange'leri için write
   izni gereklidir (test vhost regex'ine eklendi: `blog\.(agent\.events|agent\.retry\.[0-9]+s)`;
   üretim vhost izin güncellemesi declarer/admin kararı → B11 notu).

## 10. Bilinen sınırlar ve bütünleştirme notları

- **Bütünleştirme fazında koşulacak:** gerçek B6 store + gerçek worker ile uçtan uca
  iptal yarışı (claim↔cancel↔complete), backend outbox → agent.control.q gerçek
  taşıma, `AgentRunDeadlineReaper` için Infrastructure hosted-service sarmalayıcısı,
  üretim vhost'unda agent_svc retry-exchange yazma izni.
- `agent.run.cancelled`/`failed` olayları B4 `OutboxRelay` ile taşınır (mevcut hat);
  B5 backend projection'ı terminal-öncelik kurallarıyla uygular (test §7 son satır).
- Tam suite'te B8'in `ContentSnapshotSyncServiceTests` testi aralıklı başarısız
  (paralel koleksiyon broker çakışması; tek başına yeşil) — B8 sahipliği, B7 dışı.
- Fixture cleanup (agent-b7-control) tam koşum sonunda aralıklı NpgsqlException
  verebiliyordu; `ClearAllPools()` + sınırlı DROP retry eklendi, son iki tam koşumda
  cleanup hatası gözlenmedi. İzole koşumlarda hiç görülmedi.

## 11. RAG kaynakları

`node docs/ai-agent-plan/source/tools/search.cjs verify` → `valid: true`
(30 kaynak / 60 parça / 23 aşama). Stage B7 sorgusu: "Retry DLQ dead letter
güvenilirliği ve iptal yarışı". Kullanılan parçalar: [RMQ-DLX#C1] (DLX redetme/TTL/
kuyruk sınırı yönlendirmesi), [RMQ-DLX#C2] (varsayılan dead-letter kayıpsız teslim
garantisi VERMEZ → confirm'lu yeniden yayın + confirm-öncesi-ACK-yok kuralının
gerekçesi), [PY-ASYNCIO#C1] (yapılandırılmış eşzamanlılık), [PY-ASYNCIO#C2]
(Task.cancel kesin iptal garantisi değildir → terminal kararının kalıcı depoda
atomikleşmesi). Modül docstring'lerinde ilgili parça kimlikleri taşınır.
