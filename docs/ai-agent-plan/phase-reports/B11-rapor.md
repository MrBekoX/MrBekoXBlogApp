# B11 Faz Raporu — Docker, CI ve hata senaryolarını tamamla

Tarih: 2026-10-12 · Sahip: B11 implementasyon agent'ı · Plan: `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` "Aşama B11" (satır 543-581)

## 1. Kapsam ve yaklaşım

Plan B11'in iki ayağı gerçek bileşenlerle (RabbitMQ 4.2.9 + PostgreSQL 18,
test sağlayıcılı model) uygulandı ve koşuldu: **operasyon/dağıtım katmanı**
(compose, health ayrımı, CI) ve **hata senaryoları + bileşik uçtan uca**.
Plan metni satır satır okundu; görev özetindeki sayılar bağlam içindir (L003).

RAG: `search.cjs verify` → `valid:true` (30 kaynak/60 parça/23 aşama);
`search --stage B11 --query "Docker Compose RabbitMQ client kaynak yaşam
döngüsü ve cache memory" --format prompt` ile CONTEXT alındı; teknik
iddialarda [RMQ-DOTNET#C1], [RMQ-DOTNET#C2], [DOCKER-COMPOSE#C2] notları
kullanıldı.

## 2. Teslim edilen dosyalar

| Alan | Dosyalar |
| --- | --- |
| Health ayrımı (additive API) | `src/backend/Presentation/API/Health/AgentHealthOptions.cs`, `AgentBrokerHealthCheck.cs`, `AgentOutboxBacklogHealthCheck.cs`, `AgentHealthResponseWriter.cs`; `Extensions/ObservabilityExtensions.cs` (+kayıtlar), `Program.cs` (+4 endpoint map) |
| Compose (gerekçeli değişiklik) | `docker/docker-compose.yml` (sürüm kilidi + backend healthcheck `/health/live` + rabbitmq sıralama bağımlılığı + karar yorumları) |
| CI (additive) | `.github/workflows/ai-agent-ci.yml` (yeni; mevcut `ci-cd.yml`'e dokunulmadı) |
| .NET B11 E2E | `src/backend/Presentation/Api.Tests/Messaging/E2E/AgentE2eFixture.cs`, `AgentE2eFullPathTests.cs` |
| Python B11 E2E | `src/services/ai-agent-service/tests/e2e/{__init__,conftest,harness,test_e2e_composite}.py` |
| Operasyon rehberleri | `docs/ai-agent-plan/operations/{README,yerel-calistirma,topoloji-ve-surum-kilidi,schema-migration,dlq-inceleme-ve-replay,yedekleme-geri-yukleme,surum-gecisi-rollback,pgvector-karari}.md` |
| Rapor | `docs/ai-agent-plan/phase-reports/B11-rapor.md` (bu dosya) |

Dokunulmayan donuk alanlar: `src/contracts/agent/**`, `app/messaging/contracts/**`,
`Common/Messaging`, `agent_core/**` davranışı, A10 dosyaları.

## 3. Gerçek sonuçlar (koşum kaydı)

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| RAG doğrulama | `node docs/ai-agent-plan/source/tools/search.cjs verify` | `valid: true` (30/60/23) |
| API derleme | `dotnet build src/backend/Presentation/API/API.csproj -v q` | 0 Hata |
| Health uçları | API 5199'da çalışırken curl (4 uç) | `health`=200, `health/live`=200, `health/ready`=200, `health/agent`=200 + JSON gövde |
| Health ayrımı (broker DOWN) | `docker exec blogapp-rabbitmq rabbitmqctl stop_app` → curl | `live`=200, `ready`=200, **`agent`=503 Unhealthy** (broker entry Unhealthy); `start_app` sonrası `agent` → Healthy |
| Compose doğrulama | `docker compose -f docker/docker-compose.yml config --quiet` | geçerli |
| Sürüm kilidi | `docker pull rabbitmq:4.2.9-management` + imge Id karşılaştırma | pinned tag = çalışan imge (sha256:9e9fd21d…) — pin işlemsiz güvenli |
| pgvector tag | `docker manifest inspect pgvector/pgvector:pg18` | tag mevcut (bkz. §pgvector) |
| CI YAML | python `yaml.safe_load` | 3 job (dotnet-fast, python-fast, integration) + tetikleyiciler ayrıştı |
| CI dotnet hızlı katman (aynı komut) | `dotnet test … --filter "…SeoDocumentsTests\|…AgentResumeEnvelopeComposerTests\|…AgentMessagingBrokerContractMirrorTests\|…AgentContentEventServiceTests\|…AgentRunProjectionRuleTests"` (Release) | **23/23 başarılı, 937 ms** |
| CI python hızlı katman (aynı komut) | `python -m pytest tests -q --ignore=<9 broker/DB dizini>` | **621 passed, 1 skipped, 10.31 s** |
| .NET B11 E2E | `dotnet test … --filter FullyQualifiedName~Messaging.E2E` | **4/4**; art arda 2 koşum yeşil (istikrar) |
| Python B11 E2E | `python -m pytest tests/e2e -q` | **5/5**; art arda 2 koşum yeşil |
| **GATE python** | `python -m pytest tests -q` (tam suite) | **824 passed, 1 skipped** (402 s) |
| **GATE dotnet** | `dotnet test src/backend/Presentation/Api.Tests/...csproj --no-build -v q` (tam suite, seri koşum) | **205/205 başarılı** (4 m 34 s) |

Koşum disiplini: python tam suite ile dotnet tam suite SIRALI koşturuldu
(L009); B11 e2e paketleri kendi vhost'larını kullanır (python
`blogapp_w7_b11`, .NET `blogapp_w7_b11net`) ve scratch DB'leri koşum başına
benzersizdir (`blogdb_agent_b11_e2e`, `blogdb_b11e2e_<epoch>`).

## 4. Health endpoint ayrımı (plan satır 561-562)

| Uç nokta | Tag/öncül | Soru | Broker kesintisinde |
| --- | --- | --- | --- |
| `GET /health/live` | predicate yok (bağımlılık denetimi yok) | süreç yanıtlıyor mu | **200** — container restart edilmez (K3) |
| `GET /health/ready` | `ready` (npgsql+redis) | trafiğe hazır mı | **200** — kabul yolu DB'dir |
| `GET /health/agent` | `agent` (broker + outbox backlog) | agent hattı çalışıyor mu | **503** — operatör sinyali |
| `GET /health` | tümü | eski davranış | (korundu) |

`/health/agent` JSON gövdesi `AgentHealthResponseWriter` ile `pending_count`,
`oldest_pending_age_minutes` ve eşikleri taşır — "broker kapalıyken kabul
edilen iş BEKLEMEDE" durumunun izlenebilir karşılığı. Backlog kontrolü
Pending + bayat Claimed (lease'i dolmuş) kayıtları sayar; 2 dk grace,
sayı/yaş eşikleri `AgentHealth` section'ından yönetilir. Broker kontrolü
paylaşımlı uzun ömürlü bağlantıyı denetler, kendi bağlantısını açmaz
([RMQ-DOTNET#C1]).

Kabul sınırı (satır 562 "backlog kapasitesine göre kabulü sınırlayabil"):
B7 `AgentAcceptanceSettings.MaxActiveRunsTotal` zaten kapı düzeyinde
uygulanıyor (`AgentBackpressureTests.Accept_WhenSystemCapacityFull_IsRejected` —
koşumda yeşil); B11 bunu health raporlamasıyla birleştirdi, yeni bir sınır
koymadı.

## 5. Docker/operasyon kararları

1. **Sürüm kilidi:** broker imgesi `rabbitmq:4.2-management` (yüzen etiket)
   → `rabbitmq:4.2.9-management` (sabit). İstemciler zaten kilitliydi:
   `RabbitMQ.Client 7.2.2` (BuildingBlocks.csproj:13), `aio-pika >=9.5,<10`
   (pyproject:13). Pinned tag'in çalışan imgeyle birebir olduğu pull+Id
   karşılaştırmasıyla doğrulandı — değişiklik çalışan ortamda risksizdir.
2. **Management UI ağ sınırı:** AMQP ve management portları 127.0.0.1'e
   bound (mevcut durum korundu + compose yorumu + üretim kuralı rehberde).
3. **Backend healthcheck:** `/health` → `/health/live` (liveness yalnız süreç
   sorusu; broker kesintisi restart üretmez). `depends_on: rabbitmq:
   service_healthy` yalnız başlangıç sıralaması içindir.
4. **Kalıcı volume'lar:** mevcut adlandırılmış volume'lar korundu
   (`rabbitmq_data`, `postgres_data`, …); rehberde `down -v` uyarısı.
5. **Servis kullanıcıları/vhost/TLS/erişim politikaları:** D013 izin modeli
   tablo halinde belgelendi; production TLS istemci kodu değişikliği B11
   dosya sahipliği dışı olduğundan **uygulanabilir adımlarla belgelendi,
   uygulanmadı** (`operations/topoloji-ve-surum-kilidi.md` §5).
6. **Saklama + replay penceresi:** **30 gün** kararı + bakım SQL'i
   (`topoloji-ve-surum-kilidi.md` §6). Otomatik temizleme job'ı yazılmadı
   (Infrastructure sahipliği dışı) — karar + çalıştırılabilir SQL teslimi.
7. **Şema migration + iki sürüm birlikte çalışması:** `schema-migration.md`
   (EF + Alembic sırası, geri alma) ve `surum-gecisi-rollback.md`
   (expand-contract sırası; B1 ayna fixture'larının iki-dil kanıtı).

## 6. pgvector kararı — **UYGULANMADI**

Kanıt: `app/agent_core/content/pgvector.py:69-70` kuruluşta `PortError`
yükseltir (iskelet); pyproject'te sürücü yok; `agent.content_chunk` Alembic
0001→0003'te yok; gerçek embedding sağlayıcısı yok. **Düşük riskli değil.**
Compose imgesi değiştirilmedi; uygulama adımları + rollback
`operations/pgvector-karari.md`'de yazılıdır (`pgvector/pgvector:pg18` tag'inin
registry'de varlığı `docker manifest inspect` ile doğrulandı — karar
alındığında hazır yol).

## 7. Bileşik uçtan uca (birleşik kapının bileşeni)

**Bölünmenin gerekçesi (dürüst raporlama):** hat iki dilde koşar; python
worker'ının .NET test sürecinden alt süreçle çalıştırılması, üretim
giriş noktası (test sağlayıcı işaretli entrypoint) agent_core/app
sahipliklerinde olmadığı ve donuk olduğu için yapılabilir değildi. Bu yüzden
birleşik yol, GERÇEK broker'ı ortak kablo kabul ederek iki koordineli suite'te
doğrulanır; her yarım öbür yarımın kablo sözleşmesini donuk B1 şemasıyla
denetler.

**Python yarımı** (`tests/e2e`, gerçek broker+postgres, `is_test_double` model):
backend-rolü komut yayını → gerçek `BrokerConsumer`+`IntakeService` (B1
doğrulama → inbox → iş+outbox TEK transaction → ACK) → gerçek relay → gerçek
`ExecutionWorker` (gerçek graph + FakeModelProvider) → gerçek
`AgentEventPublisher` → relay → kabloda terminal olay (run_id/correlation/
event_sequence korunumu). + AYNI message_id yenileme tekilleştirmesi; + cancel
yolu (gerçek control consumer → queued→cancelled TEK transaction, worker artık
claim edemez); + kaldırılmış içerik stale_snapshot reddi (yürütme başlamadan);
+ gerçek broker kesintisinde outbox beklemesi ve toparlanma.

**.NET yarımı** (`Api.Tests/Messaging/E2E`, gerçek broker+postgres): gerçek
`AcceptAgentRunCommandHandler` (oturum→makale erişimi→snapshot→outbox TEK
transaction) → gerçek `OutboxRelayService` (confirm) → kablodan komut çekimi +
`AgentContractValidator` doğrulaması → agent_svc rolüyle
mode_selected/completed olayları → gerçek `AgentEventProjectionConsumer` →
gerçek `GetAgentRunQueryHandler` kaynaklı cevap + atıf döner; replay
(`GetAgentRunEventsQueryHandler`) aynı sonucu taşır; ACK sonrası kuyruk boşalır.
+ iptal yolu (gerçek `CancelAgentRunCommandHandler` → cancel komut kabloda →
cancelled terminal → EŞİT sequence'li geç completed stale sayılır — kural:
AgentRunEventProjectionRules.cs:24-26 "iki terminal çelişirse yüksek sequence
kazanır"); + kaldırılan içeriğe dayanan geç sonuç GET'te maskeli
(UnavailableReason, cevap sızmaz); + broker kesintisinde 3 kabul → `Accepted`
(bekliyor) → toparlanma → tüm komutlar kabloda.

**Bilinen sınırlama (açık):** "kaynaklı cevap"ın citation üreten yarımı
python graph'ında test sağlayıcıyla ÜRETİLEMEZ (B6 raporu kuralı: article
kapsamda citation'sız cevap completed'a çevrilmez); citation'lı sourced-answer
yarımı .NET suite'inde kablo üzerinden (agent rolü, B5 payload sözleşmesi)
doğrulanır. Gerçek model davranışı hiçbir suite'te iddia edilmez.

## 8. 12 hata senaryosu — konsolide harita

Tümü gerçek broker+postgres üzerinde koşuldu; GATE koşumunda yeşil
(§3 tablosu). "Yeni" = B11'de yazıldı.

| # | Senaryo (plan 568-579) | Test(ler) — dosya | Sonuç |
| --- | --- | --- | --- |
| 1 | Publish öncesi backend crash | `TransactionWithoutCommit_PersistsNoRunAndNoCommand` + `Accept_LosingUniqueTurnRace_RollsBackGhostCommand` (Outbox/AgentOutboxRelayTests.cs) | PASS |
| 2 | Confirm kaybı | `ConfirmLoss_RedeliversOnlyWithSameMessageId` (aynı dosya; aynı message_id + monoton delivery_attempt) | PASS |
| 3 | Python commit öncesi/sonrası crash | `test_precommit_crash_is_recovered_by_redelivery`, `test_postcommit_crash_does_not_duplicate_job`, `test_redelivery_same_message_id_is_inbox_idempotent` (intake/test_intake_accept.py) | PASS |
| 4 | Uzun işte worker restart | `test_worker_kill_and_restart_resumes_from_checkpoint` (worker/test_worker_lifecycle.py), `test_lease_renewal_refusal_aborts_execution_midflight`, `test_live_worker_with_lost_lease_cannot_overwrite_new_owner` (worker/test_worker_contention.py) | PASS |
| 5 | Sonuç outbox commit sonrası crash | `test_complete_job_writes_terminal_outbox_in_same_transaction` (worker/test_job_store_claims.py), `test_relay_failure_keeps_record_pending_with_error` (intake/test_outbox_relay.py) + yeni `test_e2e_broker_outage_outbox_accumulates_then_recovers` | PASS |
| 6 | Projection commit sonrası ACK kaybı | `ConnectionLoss_EventPublishedWhileConsumerDown_IsReplayedOnce` + `DuplicateDelivery_IsAppliedOnlyOnce` (Projection/AgentEventProjectionConsumerTests.cs) + yeni .NET E2E ACK-drain doğrulaması | PASS |
| 7 | Duplicate / ters sıra olaylar | `OutOfOrderDelivery_OldSequenceIsIgnored`, `OldProgress_AfterTerminal_DoesNotRegressStatus` (Projection/) + `test_older_revision_ignored_out_of_order_delivery` (content_sync/test_content_state.py) | PASS |
| 8 | Cancel/execute/completed yarışları | `test_intent_first_complete_rejected_then_cancelled`, `test_concurrent_intent_insert_vs_complete_commit_single_terminal` (integration/test_cancel_fencing_integration.py), `test_terminal_precedence_both_directions_with_worker_double` (control/), `LateCompletedEvent_AfterCancelled_DoesNotRestoreRun` (Cancel/AgentBackpressureTests.cs) + yeni .NET E2E cancel + yeni python e2e cancel | PASS |
| 9 | Broker kapalıyken outbox birikmesi + toparlanma | `BrokerOutage_AfterDbCommit_WorkNotLost_ThenPublished` (Outbox/) + **yeni** .NET `FullPath_BrokerOutage_RunsWaitVisibly_ThenBacklogRecovers` + **yeni** python `test_e2e_broker_outage_outbox_accumulates_then_recovers` (gerçek stop_app/start_app) | PASS |
| 10 | DLQ replay + süresi geçmiş işler | `test_valid_job_is_replayed_to_origin_with_same_id`, `test_expired_job_is_not_blindly_replayed` (control/test_dlq_replay.py), `test_expired_running_job_fails_with_timeout` (control/test_reaper.py) | PASS |
| 11 | Kaldırılan içeriğe dayanan geç sonuç | `ResultCitingUnpublishedArticle_IsContentUnavailable` (Content/ContentSnapshotSyncServiceTests.cs), `test_update_at_or_below_removal_revision_rejected_as_stale` (content_sync/) + **yeni** .NET `FullPath_RemovedContent_LateResultIsMaskedWithReason` + **yeni** python `test_e2e_removed_content_rejects_stale_command` | PASS |
| 12 | İki servis sürümü aynı sözleşmelerle | B1 ayna katmanı: `AgentContractFixtureTests`+`AgentMessagingBrokerContractMirrorTests` (.NET) ↔ `test_messaging_contracts_fixtures.py`+`test_messaging_contracts_rules.py` (38 ortak fixture, iki dil birebir) + her iki e2e suite'inin kablo sözleşme doğrulaması | PASS |

## 9. Test raporu — bilinen sınırlamalar ve recovery

**Sınırlamalar (iddia edilmeyenler):**
1. Gerçek LLM/embedding sağlayıcısı devrede değil; model yolu `is_test_double`
   işaretli sağlayıcı + kablo sözleşmesi doğrulamasıdır. "Test sağlayıcı
   üretimde etkinleştirilemez" kuralı aynen geçerlidir.
2. Canlı deployment kapsam dışıdır (görev kapsamı); rollout/rollback yalnız
   rehber olarak teslim edildi.
3. CI workflow'u GitHub Actions'ta ÇALIŞTIRILMADI (yerel ortamda Actions yok):
   YAML ayrıştı; iki hızlı-katman komutu yerelde AYNEN koşuldu (23/23 ve
   621/1skip); integration job'ın service-container bekleme süreleri ilk
   gerçek koşumda ayarlanabilir. `ci-cd.yml`'deki bayat yollar
   (`src/BlogApp.Server` gibi) kapsam dışı bulgu olarak kaydedildi — o dosya
   additive kuralına tabiydi.
4. TLS ve otomatik saklama temizliği kod olarak uygulanmadı (dosya sahipliği
   dışı) — uygulanabilir karar dokümanı olarak teslim edildi (§5.5, §5.6).
5. pgvector uygulanmadı (§6).

**Recovery adımları** (özet; ayrıntı operations/ altında):
broker kapalı → `rabbitmqctl start_app`, relay otomatik boşaltır; DLQ birikimi
→ `dlq-inceleme-ve-replay.md` (peek → uygunluk → replay/red); şema uyumsuzluğu
→ `schema-migration.md`; veri kaybı → `yedekleme-geri-yukleme.md`; kötü release
→ `surum-gecisi-rollback.md` (migration geri alınmaz, image geri alınır).

## 10. Ortam olayları ve ders uygulaması

- Koşum sırasında API derlemesini eski çalışma sürecinin exe kilidi blokladı
  (MSB3027) — B9 F2 dersi uygulandı: süreç sonlandırılıp yeniden derlendi.
- E2E geliştirme sırasında 3 gerçek bulgu düzeltildi: (a) drain bağlantısının
  varsayılan vhost'a gitmesi → fixture vhost'una taşındı (L009 izolasyon
  hatası yakalayan test); (b) mode_selected olayının zorunlu alanı
  (`requires_web_search`) DLQ'ya düşmüştü → gerçek şemaya uygun zarf;
  (c) cancel consumer'a JobStore yerine ControlStore verilmeli —
  gerçek-bileşen testi bu karışımı yakaladı.
- `pytest -q tests/e2e` bir kez nested-loop hatasıyla düşmüştü (wait_until
  koşulu içinde `run()`), düzeltildi — paylaşımlı loop kuralı (B4 deseni)
  yeni pakete de uygulandı.

## 11. Sonraki adımlar (orchestrator'a)

- progress.md B11 satırı: **Doğrulandı** (bu raporun §3 kanıtlarıyla).
- Birleşik kapı: B11 bileşenleri hazır; gerçek model sağlayıcısı gelmeden
  kapının "gerçek model" maddeleri koşulamaz (main-prompt kuralı).
- CI'ın ilk GitHub Actions koşumu izlenmeli (§9.3).
