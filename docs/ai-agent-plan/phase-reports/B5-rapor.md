# B5 Faz Raporu — Agent olaylarını yayınla ve backend projectionını oluştur

Tarih: 2026-10-12 · Dal: `feature/ai-agent-integration` · Sahip: B5 implementasyon agent'ı

Plan kaynağı: `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` "Aşama B5" (satır 339-366).
Kararlar: D011 (migration sahipliği), D013 (declarer kimliği), D014 (Python bağımlılık kilitleri).
RAG aracı faz başında doğrulandı: `node docs/ai-agent-plan/source/tools/search.cjs verify` →
`valid: true` (30 kaynak, 60 parça). B5 CONTEXT'i
`search.cjs search --stage B5 --query "Sonuç olayları duplicate ve SignalR progress yayını" --format prompt`
ile getirildi; kullanılan kaynaklar: [SIGNALR-HUBS#C1/#C2], [ENG-OUTBOX#C2], [RMQ-RELIABILITY#C1],
[LG-STREAMING#C1/#C2]. Hub'da durum tutulmaması ve IHubContext üzerinden background yayın
kararı bu kaynaklara dayanır; kalıcı tamamlama replay'i B10'a bırakılmıştır (plan kuralı:
"SignalR gönderildi bilgisini kullanıcı okudu garantisi sayma").

## 1. Python tarafı (agent → broker olay yayını)

### 1.1 Migration 0002 (`migrations/versions/20261012_0002_run_event_sequences.py`)

- `agent.run_event_sequences` (run_id PK, last_sequence, updated_at): run başına atomik
  event_sequence tahsis tablosu. `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` tek satır
  kilidi altında tahsis yapar; eşzamanlı yayıncılar duplicate/ters sequence ÜRETEMEZ
  (plan: "Olay sırası için run başına atomik event_sequence üret"). B4'ün accepted olayı
  sequence 0 olduğundan tahsis 1'den başlar.
- `ck_jobs_status` genişletildi: `accepted` + terminal değerler
  (`completed, partially_completed, failed, cancelled`). Kısıt genişlemesi veri
  kaybettirmez; terminal sonucun iş durumuyla outbox kaydını aynı transaction'da yazması
  için gereklidir. `needs_input` bilinçli YOKTUR: terminal değildir, iş durumu accepted kalır.
- Doğrulama: scratch DB `blogdb_agent_migcheck` üzerinde `upgrade head → downgrade 0001 →
  upgrade head` programatik Alembic koşusu başarılı (bu ask içinde çalıştırıldı; scratch DB
  sonrasında düşürüldü).

### 1.2 `app/messaging/events.py` — `AgentEventPublisher` (yeni)

Plan listesinin birebir karşılığı:

- **DomainProgress → broker olayı:** `publish_progress` → `agent.run.progressed`
  (`AgentRunProgressedV1` B1 modeliyle kurulur; şema uyumu pydantic doğrulayıcılarıyla).
- **Terminal sonuç → sürümlenmiş olaylar:** `publish_outcome(AgentOutcome)` →
  `agent.run.completed | partially_completed | failed | cancelled` (tam snapshot payload'ı;
  completed/partially_completed için answer XOR report, source_scope + usage + selected_mode
  zorunluluğu EventPublishError ile uygulanır).
- **Kritik durum + terminal aynı transaction:** `publish_outcome` içinde
  `UPDATE agent.jobs SET status=... WHERE status IN ('accepted')` ile outbox INSERT tek
  transaction'da; iş zaten terminal ise `AlreadyTerminal` — ikinci terminal olay üretilmez ve
  sıra tahsisi rollback ile geri alınır (duplicate terminal üretilmez).
- **Kaynak/kapsam kontrolü:** `source_scope=article` + web citation (veya tersi) ve
  scope'a citation taşımama → `EventPublishError`; hiçbir kayıt yazılmaz (test:
  `test_inconsistent_source_scope_result_is_not_published`).
- **Seyrekleştirme:** aynı run'da AYNI `kind` progress `min_progress_interval_seconds`
  (varsayılan 2.0s) içinde tekrar gelirse üretilmez (`ThrottledProgress`); kayıt yazılmaz,
  sıra tüketilmez. `mode_selected`/`needs_input`/terminal seyrekleştirilmez. Token başına
  broker mesajı bu katmana gelmez (token akışı B6 worker'da DomainProgress'e dönüştürülmez).
- **Birebir B1:** tüm zarflar `parse_envelope` ile geri doğrulanabilir (test kanıtı);
  `requires_web_search` yalnız `deep_research`'te true olabilir (B1 çapraz kuralı,
  `test_mode_selected_web_flag_only_for_deep_research`).

### 1.3 OutboxRelay (B4 genişletmesi)

Relay zaten türden bağımsızdı; B5'te claim sırasına deterministik kırıcı eklendi
(`job_store.py:417` `ORDER BY created_at, outbox_id`) ve docstring güncellendi. Confirm
sonrası `published_at` yazımı B4 davranışıdır; B5 testleri bunu progress/terminal olaylarıyla
kanıtlar (`test_relay_marks_rows_published_and_second_run_claims_nothing`).

## 2. .NET tarafı (broker → projection → SignalR)

### 2.1 Domain (ADDITIVE)

- `AgentEventInbox` entity (yeni, `Core/Domain/Entities/AgentEventInbox.cs`): PK
  (ConsumerName, MessageId); consumer kapsamlı mesaj tekilliği DB'de keser — tekrar teslimde
  projection yeniden UYGULANMAZ.
- `AgentRunStatus` enum genişletmesi (ADDITIVE; Accepted=0 değişmez): Completed=1,
  PartiallyCompleted=2, Failed=3, Cancelled=4 + `AgentRunStatusRules.IsTerminal()`.
  Non-terminal olaylar (progress/mode_selected/needs_input) Status'u DEĞİŞTİRMEZ; böylece B3
  kabul akışındaki `Status == Accepted` aktif-iş sayımı doğru kalır (handler değişmedi).
- `AgentRun` projection kolonları (additive): `LastEventSequence` (default 0),
  `SelectedMode`, `SourceScope`, `ResultJson` (terminal snapshot, jsonb), `TerminalAt`.

### 2.2 EF migration `AddAgentEventInbox` (20261011231654)

`dotnet ef migrations add` ile üretildi (tasarım zamanı bağlantısı
`BLOGAPP_MIGRATION_CONNECTION` env'den; değer log'a yazılmadı). İçerik tamamen additive:
yeni tablo `agent_event_inbox` (PK composite + 2 index) ve `agent_runs`a 5 yeni kolon.
Snapshot diff: +62 satır, −0. Mevcut kolon/tablo değişikliği YOK (yorum: "mevcut tablolar
değişmez" kuralı "yıkıcı şema değişikliği yok" olarak yorumlandı — projection'ın AgentRun
durumunu yazması plan gereğidir; alternatif ayrı projection tablosu Status enum
genişletmesini anlamsızlaştırırdı).

### 2.3 Projection (Application)

- `AgentRunEventProjectionRules.cs` (saf çekirdek): Duplicate (inbox'ta var) / Stale
  (sequence ≤ son uygulanan VEYA terminal run'da non-terminal olay) / Apply. Terminal-öncelik:
  "geç gelen eski olay terminal durumu geriye götürmez"; çelişen iki terminalde YÜKSEK
  sequence kazanır (teslim sırasına güvenilmez).
- `AgentRunEventProjectionHandler.cs`: olay doğrulaması consumer'da (B1
  `AgentContractValidator`); handler **inbox kaydı + AgentRun projection değişikliğini TEK
  transaction'da** yapar: `IUnitOfWork.ExecuteResilientAsync` + ReadCommitted transaction +
  `SELECT ... FOR UPDATE` (run satırı kilitlenir; eşzamanlı teslimler sıralanır; lock
  sonrası ikinci tekrar kontrolü). Sonuçlar: applied/stale/quarantined inbox satırı; Apply
  kararında `AgentRunNotification` üretilir (yalnız commit'ten sonra — plan: "commit edilmiş
  projection üzerinden UI bildirimi").
- **Bilinmeyen run_id sınırlı politikası:** sonsuz retry/DLQ döngüsü yerine kalıcı
  `quarantined` inbox kaydı yazılır, mesaj ACK'lanır (görünür, sorgulanabilir, B7
  genişletebilir). Test: `UnknownRun_EventIsQuarantinedAndAcked`.
- Bildirim soyutlaması `IAgentRunNotifier` + `AgentRunNotification`
  (`Core/Application/Common/Messaging/AgentRunNotification.cs`): hub türü Presentation'da
  olduğundan Application arayüz konuşur.

### 2.4 Consumer hosted service (Infrastructure)

- `AgentEventProjectionConsumer.cs`: `RabbitMqAgentConsumer` (B2 tabanı) +
  `backend.agent.events.q`. Akış: B1 `AgentContractValidator.Validate(body)` → registry DTO
  çözümlemesi (+ ExtensionData = extra field reddi) → türe göre projection girdisi → handler →
  **commit'ten sonra temel sınıf ACK eder** (base ACK, HandleAsync normal dönüşünden sonra).
- Kalıcı sözleşme ihlali → istisna → temel sınıf `BasicNackAsync(requeue:false)` → DLX
  (sürekli requeue yok; test: `ContractViolation_GoesToDeadLetterWithoutProjectionChange`).
- Geçici DB hatası da B2 tabanıyla DLX'e düşer — transport retry ayrımı **B7 kapsamıdır**
  (bilinçli B5 sınırı, aşağıda açık bulgular).
- UI bildirimi projection commit'inden SONRA best-effort; bildirim hatası ACK'ı engellemez.
- `AgentEventProjectionDependencyInjection.cs`: `AddAgentEventProjection()` — no-op notifier
  (TryAdd), validator, handler (scoped), consumer (singleton), hosted service. B6/B10
  Program.cs'e bağlayacak; bu fazda API'de kayıtlı DEĞİL (izin yalnız hub kaydıdır).

### 2.5 SignalR ince yayın katmanı (Presentation)

- `Hubs/AgentRunsHub.cs` (yeni): `SubscribeToRun/UnsubscribeFromRun(runId)` — run_id kanonik
  UUID doğrulaması ([SIGNALR-HUBS#C1]: hub'da durum tutulmaz). Grup: `run:{run_id}`.
  Map: `/hubs/agent-runs` (AllowAnonymous — bkz. açık bulgu F3).
- `Services/SignalRAgentRunNotifier.cs`: `IHubContext<AgentRunsHub>` ile commit edilmiş
  projection olaylarını `RunUpdated` olarak gruba yayınlar ([SIGNALR-HUBS#C2]); terminal
  olaylarda `result` alanı tam snapshot'ı taşır.
- `Program.cs`: yalnız iki minimal hub kaydı satırı (notifier DI + MapHub).

## 3. Testler (gerçek broker + gerçek postgres)

### Python — `src/services/ai-agent-service/tests/events/` (yeni paket, __init__.py'li)

Ortam: ayrı vhost `blogapp_dev_b5` (B4'ün b4 vhost'u ve B2/B3'ün blogapp_dev'i ile kuyruk
paylaşımı yok), scratch DB `blogdb_agent_b5tests`, aynı Alembic zinciri programatik uygulanır.
Parolalar docker/.env'den okunur; kod/fixture/log'a girmez.

| Kabul ölçütü | Test kanıtı |
| --- | --- |
| atomik event_sequence | `test_concurrent_publishers_cannot_duplicate_or_regress_sequence` (12 eşzamanlı yayıncı → 1..12 aralıksız); `test_progress_events_get_atomic_contract_valid_sequences` |
| kritik durum + terminal aynı transaction | `test_terminal_outcome_writes_job_status_and_outbox_atomically`; `test_second_terminal_event_is_never_produced` (duplicate terminal yok) |
| kaynak/kapsam kontrolü | `test_inconsistent_source_scope_result_is_not_published` (yayın reddi, hiçbir kayıt yok) |
| seyrekleştirme | `test_progress_throttles_same_kind_but_keeps_transitions` (aynı kind throttle, farklı kind geçer) |
| relay: tüm olay türleri → confirm → published | `test_relay_publishes_progress_and_terminal_events_to_backend_queue` (gerçek broker, kuyruktan zarf geri okuma + parse_envelope), `test_relay_marks_rows_published_and_second_run_claims_nothing`, `test_relay_preserves_outbox_creation_order`, `test_relay_publishes_terminal_snapshot_with_full_result` |
| B1 birebirlik | her zarf testte `parse_envelope` ile geri doğrulanır; web-only kuralı `test_mode_selected_web_flag_only_for_deep_research`; needs_input accepted bırakır (`test_needs_input_keeps_job_accepted`) |

### .NET — `src/backend/Presentation/Api.Tests/Messaging/Projection/` (yeni)

Ortam: postgres `blogdb_b5tests` (izole, migrate edilir) + broker vhost `blogapp_dev_b5net`
(management API ile provizyon, retry'lı; declarer admin kimliği — D013). Olaylar gerçek
`agent_svc` rolüyle `blog.agent.events`'e yayınlanır; tüketim gerçek B2 consumer tabanıyla.

| Kabul ölçütü | Test kanıtı |
| --- | --- |
| duplicate yeniden uygulanmaz | `DuplicateDelivery_IsAppliedOnlyOnce` (aynı mesaj iki kez; inbox 1 satır, LastEventSequence=1, tek bildirim) |
| ters sıra | `OutOfOrderDelivery_OldSequenceIsIgnored` (seq2 sonra seq1 → stale, gerileme yok) |
| terminal sonrası eski progress | `OldProgress_AfterTerminal_DoesNotRegressStatus` (Status Completed kalır) |
| bağlantı kaybı sonrası replay | `ConnectionLoss_EventPublishedWhileConsumerDown_IsReplayedOnce` (tüketici yokken yayın → durable kuyrukta bekler → ikinci bağlanışta replay → tek uygulama, ikinci tüketici 0 olay) |
| bilinmeyen run quarantine | `UnknownRun_EventIsQuarantinedAndAcked` (+ broker'sız `AgentRunProjectionHandlerTests.UnknownRun_IsQuarantined_WithoutThrowing`) |
| sözleşme ihlali → DLX | `ContractViolation_GoesToDeadLetterWithoutProjectionChange` |
| mutlu yol + commit sonrası bildirim | `RunEvents_AreProjected_Through_RealBroker` (3 olay, Status/sequence/snapshot/scope + 3 bildirim) |
| saf terminal-öncelik kuralları | `AgentRunProjectionRuleTests` (7 test) |

### Gate komutları (bu ask içinde çalıştırıldı)

| Komut | Sonuç |
| --- | --- |
| `python -m pytest tests/events -q` | **13 passed** |
| `python -m pytest tests/intake tests/events -q` | **27 passed** |
| `python -m pytest tests -q --ignore=tests/qa --ignore=tests/state` | **433 passed, 1 skipped** |
| `python -m pytest tests/qa tests/state -q` | **93 passed** |
| `dotnet test src/backend/Presentation/Api.Tests --nologo -v q` | **106/106 Başarılı** (B1+B2+B3+B5; 1 m 48 s) |

B4 regresyonu: `tests/intake/test_migrations_smoke.py` Alembic head pin'i "0001"→"0002"
güncellendi + `run_event_sequences` tablo beklentisi eklendi (zincir sahibi B5 olarak
yapılan meşru entegrasyon güncellemesi; testin amacı "şema head'de" iddiasını korur).

## 4. Bulgular

| ID | Severity | Dosya | Bulgu | Çözüm/Doğrulama |
| --- | --- | --- | --- | --- |
| F1 | orta (test sahipliği) | `Api.Tests/.../AgentEventProjectionConsumerTests.cs` (UnknownRun) | Test yayıncısı messageId'yi yalnız AMQP property'sine yazmış, gövdeye yazmamış; projection gövdeyi esas aldığından poll doğru satırı bulamıyordu. Kanıt: consumer teslim log'u (gövde message_id) ↔ row karşılaştırması. | messageId her iki katmana da yazıldı; suite 16/16 yeşil. Ders: AMQP property message_id ile gövde message_id ayrı katmanlardır; handler sözleşme gereği gövdeyi esas alır. Ana agent'ın lessons-learned'e alması önerilir. |
| F2 | düşük | `AgentEventProjectionFixture.cs` (QueueDepth/Purge) | Kuyruk yoklaması argümansız AKTİF declare ile PRECONDITION_FAILED üretti (DLX'li kuyruk). | Pasif declare'a çevrildi; suite yeşil. |
| F3 | orta (güvenlik, B9/B10) | `Presentation/API/Hubs/AgentRunsHub.cs` | Hub şu an AllowAnonymous; run_id 128-bit unguessable olsa da yetkisiz abonelik B10'da auth/sahiplik bağlanana kadar açık. | Bilinçli B5 sınırı: plan hub'ı "ince yayın katmanı" olarak tanımlar, replay/auth B9-B10'da. Açık kayıt. |
| F4 | düşük (B7 kapsamı) | `Infrastructure/Messaging/AgentEventProjectionConsumer.cs` | Geçici DB hatası da DLX'e düşer (B2 taban davranışı); hedefe özel gecikmeli retry yok. | Plan B7: "Transport hatası, kalıcı sözleşme hatası ve graph yürütme hatasını ayır" — bilinçli devir. |
| F5 | bilgi | `AgentEventProjectionConsumer.cs` (action.proposed) | `agent.action.proposed` olayı projection'da yalnız inbox+bildirim üretir; öneri saklaması B9'a aittir. | Açık kayıt. |

## 5. Kapsam dışı bırakılanlar (plan gereği)

Worker (B6), retry/DLQ politikası (B7), UI replay GET uç noktaları (B10), gerçek tarayıcı
istemciyle SignalR uçtan uca testi (B10/UI), agent_core/** ve A6/A7 dosyaları, REST
endpoint'leri. Notifier tarayıcı testi yerine RecordingNotifier ile kanıtlandı; gerçek
tarayıcı doğrulaması çalıştırılmadı (raporda açık).

## 6. Dosya envanteri

Yeni (Python): `app/messaging/events.py`, `migrations/versions/20261012_0002_run_event_sequences.py`,
`tests/events/{__init__,conftest,test_event_publisher,test_event_relay}.py`
Yeni (.NET): `Core/Domain/Entities/AgentEventInbox.cs`,
`Core/Application/Common/Messaging/AgentRunEventProjectionRules.cs`,
`Core/Application/Common/Messaging/AgentRunNotification.cs`,
`Core/Application/Features/AgentFeature/Events/AgentRunEventProjectionHandler.cs`,
`Infrastructure/Infrastructure/Messaging/AgentEventProjectionConsumer.cs`,
`Infrastructure/Infrastructure/Messaging/AgentEventProjectionDependencyInjection.cs`,
`Infrastructure/Infrastructure/Persistence/Configurations/AgentEventInboxConfiguration.cs`,
`Infrastructure/Infrastructure/Persistence/Migrations/20261011231654_AddAgentEventInbox{,.Designer}.cs`,
`Presentation/API/Hubs/AgentRunsHub.cs`, `Presentation/API/Services/SignalRAgentRunNotifier.cs`,
`Presentation/Api.Tests/Messaging/Projection/*` (4 dosya)
Değişen: `Core/Domain/Enums/AgentRunStatus.cs`, `Core/Domain/Entities/AgentRun.cs`,
`Core/Application/Common/Interfaces/Data/IApplicationDbContext.cs`,
`Infrastructure/.../AppDbContext.cs`, `Infrastructure/.../AgentRunConfiguration.cs`,
`Infrastructure/.../AppDbContextModelSnapshot.cs` (+62/−0),
`Presentation/API/Program.cs` (2 satır hub kaydı),
`app/messaging/__init__.py` (export), `app/messaging/job_store.py` (1 satır sıra kırıcı),
`app/messaging/outbox.py` (docstring), `tests/intake/test_migrations_smoke.py` (head pin).

## 7. Özet

B5 kabul ölçütleri — duplicate, ters sıra, terminal sonrası eski progress ve tarayıcı
bağlantı kaybı senaryoları — gerçek broker + gerçek postgres üzerinde karşılıklı iki dilde
kanıtlandı (Python 13 + .NET 16 B5 testi; toplam suite'ler 527 python / 106 dotnet yeşil).
Donuk B1 sözleşmeleri ve B2-B4 altyapısı yalnız tüketildi; migration'lar additive'dir.
Faz, orchestrator'ın progress.md/decisions.md kaydı ve (istemesi halinde) F1 dersinin
lessons-learned'e alınması ile kapanmaya hazırdır.
