# B3 Faz Raporu — Backend iş kabulü ve transactional outbox publisher

Tarih: 2026-10-11 · Faz: B3 (W3) · Sahip: B3 implementasyon agent'ı
Plan: `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` "Aşama B3" (satır 273-307), satır satır okunarak uygulandı.

## 1. Yapılan işler

### 1.1 Domain (Core/Domain)

| Dosya | İçerik |
| --- | --- |
| `src/backend/Core/Domain/Entities/AgentRun.cs` | İş kabul kaydı: `Id` = sözleşme run_id (kanonik UUID), `ConversationId` + `TurnSequence` (benzersiz çift), `OwnerKey`/`OwnerUserId`/`GuestSessionId` (sahiplik backend tarafından yazılır, plan satır 124), `IdempotencyKey` + `IdempotencyPayloadHash` (satır 289-290), immutable `ContextSnapshotJson` + `ContextSnapshotReference`, `DeadlineAt` (K6: deadline sahibi backend), `AcceptedAt`. |
| `src/backend/Core/Domain/Entities/OutboxMessage.cs` | Transactional outbox kaydı: `MessageId` (tekrar yayında korunur, satır 301), `EnvelopeJson` (byte-exact metin saklama), `Status` yaşam döngüsü, `ClaimedBy`/`ClaimedAt`/`ClaimLeaseUntil` (lease), `AttemptCount` (zarf `delivery_attempt` karşılığı), `LastError`, `PublishedAt`. |
| `src/backend/Core/Domain/Enums/AgentRunStatus.cs` | Tek değer `Accepted` — plan satır 305'in "backend'in sorumluluk alması" durumu; Python `agent.run.accepted` olayı AYRI anlamdır. Olay tabanlı geçişler B5 projection'ında bu enum'ı genişletir. |
| `src/backend/Core/Domain/Enums/AgentOutboxStatus.cs` | `Pending → Claimed → Published`; `DeadLettered` deneme üst sınırı için. |

### 1.2 Application (Core/Application)

| Dosya | İçerik |
| --- | --- |
| `Features/AgentFeature/Commands/AcceptAgentRunCommand/AcceptAgentRunCommandRequest.cs` | MediatR komutu (REST controller B10'da). |
| `Features/AgentFeature/Commands/AcceptAgentRunCommand/AcceptAgentRunCommandHandler.cs` | Kabul akışı (plan satır 285-293): ① oturum doğrulama (JWT `ICurrentUserService.UserId` veya sunucu tarafı misafir oturumu; hiçbiri yoksa unauthorized; `AllowGuestRuns=false` ise misafir forbidden) → ② makale erişimi (yalnız `PostStatus.Published`; silinmişler soft-delete filter ile dışarıda) → ③ idempotency (aynı `(OwnerKey, IdempotencyKey)` + aynı payload hash → mevcut run `Replay=true`; farklı hash → `Conflict`) → ④ konuşma sahipliği + sahip başına aktif iş limiti (`AgentAcceptanceSettings.MaxActiveRunsPerOwner`) → ⑤ `turn_sequence` = konuşma maksimumu + 1 → ⑥ immutable bağlam snapshot'ı (makale içeriğinin UTF-8 SHA-256'sı, D008; `BlogPost.Version` KULLANILMAZ, L004) → ⑦ zarf üretimi + **commit öncesi** `AgentContractValidator` doğrulaması → ⑧ `AgentRun` + `OutboxMessage` TEK transaction'da (`IUnitOfWork.ExecuteResilientAsync` + `BeginTransactionAsync(ReadCommitted)`), commit sonrası `AgentRunAcceptedDto` (satır 293). `DbUpdateException` benzersizlik yarışında: idempotency yeniden sorgusu (replay/çakışma) ya da tur çakışması için `Conflict` — hayalet komut oluşmaz. |
| `Features/AgentFeature/Commands/AcceptAgentRunCommand/AcceptAgentRunCommandValidator.cs` | FluentValidation; kurallar B1 payload sözleşmesiyle aynı (question ≤8000, dil kodu, mode_preference Choice, selected_text ≤20000). |
| `Features/AgentFeature/Commands/AcceptAgentRunCommand/AgentRunAcceptedDto.cs` | `RunId`, `ConversationId`, `TurnSequence`, `AcceptedAt`, `DeadlineAt`, `Replay`. |
| `Common/Messaging/AgentCommandEnvelopeComposer.cs` | ExecutionRequested zarfı üretimi (B1 DTO'larından; opsiyonel null alanlar taşınmaz) + `WithDeliveryAttempt` (tekrar yayında YALNIZ transport sayacı değişir, `message_id` dahil diğer alanlar korunur). |
| `Common/Interfaces/Messaging/IOutboxWriter.cs` | B0 §4 önerisi doğrultusunda Application soyutlaması; Infrastructure `EfOutboxWriter` kaydı ortam transaction'ının içine ekler. |
| `Common/Options/AgentAcceptanceSettings.cs` | `AgentAcceptance` section: `AllowGuestRuns` (K5: kota ürün kararı; varsayılan true), `MaxActiveRunsPerOwner=3`, mod bazlı deadline dakikaları (fast 2 / analysis 5 / deep_research 15 / auto 5). |
| `Common/Options/AgentOutboxRelaySettings.cs` | `AgentOutbox` section: `BatchSize=16`, `PollIntervalSeconds=2`, `ClaimLeaseSeconds=60`, `MaxClaimLeaseSeconds=600`, `ConfirmTimeoutSeconds=10`, `MaxAttempts=12`, `InstanceName`. |
| `Common/Interfaces/Data/IApplicationDbContext.cs` | ADDITIVE: `AgentRuns`, `OutboxMessages` (ve eksik olan `IdempotencyRecords`) DbSet'leri eklendi; mevcut üyeler değişmedi. |

### 1.3 Infrastructure

| Dosya | İçerik |
| --- | --- |
| `Persistence/Configurations/AgentRunConfiguration.cs` | `agent_runs` tablosu; unique `UX_agent_runs_owner_idempotency (OwnerKey, IdempotencyKey)` ve `UX_agent_runs_conversation_turn (ConversationId, TurnSequence)` — yarışları DB seviyesinde keser; string enum dönüşümü. |
| `Persistence/Configurations/OutboxMessageConfiguration.cs` | `outbox_messages`; unique `UX_outbox_messages_message_id`, claim taraması için `IX_outbox_messages_status_lease`, `IX_outbox_messages_run`. |
| `Persistence/Migrations/20261011203351_AddAgentRunAndOutbox.cs` | **Migration adı: `AddAgentRunAndOutbox`** (20261011203351). İçerik doğrulandı: yalnız 2 CreateTable + 8 CreateIndex; mevcut tablolara dokunmaz; `Down` yalnız yeni tabloları düşürür. Snapshot diff'i yalnız ekleme (+ dosya başına BOM eklendi, EF araç davranışı). |
| `Persistence/DesignTimeDbContextFactory.cs` | `dotnet ef` için deterministik tasarım zamanı context'i; bağlantı yalnız `BLOGAPP_MIGRATION_CONNECTION` env'den okunur, değeri log'a yazılmaz. Runtime davranışını değiştirmez. |
| `Messaging/OutboxClaimStore.cs` | Plan satır 297+302: `UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED) RETURNING` ile atomik lease claim; `MarkPublishedAsync` (`WHERE Status='Claimed'` guard'ı — lease dolup başka publishera geçmiş kayıt ezilmez, stale confirm ölçülür); `MarkAttemptFailedAsync` (beklemede bırakma veya `MaxAttempts` sonrası DeadLettered). |
| `Messaging/OutboxRelayService.cs` | Hosted service (satır 295-303): her döngüde claim → B2 confirm'lu publisher ile persistent+mandatory yayın → confirm sonrası Published. `WaitAsync(ConfirmTimeoutSeconds)`: confirm zaman aşımı → kayıt beklemede kalır (satır 300). Broker hatası → kayıt beklemede kalır, döngü çökmez. Lease deneme sayısıyla üstel büyür (60s→cap 600s). Publisher ilk kez bağlanana dek her döngüde tekrar dener (broker açılışta kapalı olabilir). |
| `Messaging/OutboxMetrics.cs` | Satır 303: `Meter("BlogApp.Outbox")` — `outbox.claimed/published/publish_failed/deadlettered/stale_confirm` sayaçları, `outbox.age_seconds` (kabulden yayına yaş) ve `outbox.attempts` histogramları. |
| `Messaging/AgentOutboxDependencyInjection.cs` | `AddAgentOutbox(configuration)`: options kayıtları, `IOutboxWriter`, somut `RabbitMqAgentPublisher` (komut+içerik exchange'leri, K3 yetki kapsamı), `OutboxRelayService` hosted service. |

### 1.4 Testler (Presentation/Api.Tests — gerçek Postgres + gerçek RabbitMQ)

| Dosya | Kapsam |
| --- | --- |
| `Messaging/Outbox/AgentOutboxDatabaseFixture.cs` | İzole test DB'si (`blogdb_b3tests`): her koşuda drop+create + `MigrateAsync`; testler arasında TRUNCATE; bağlantı bilgisi `BLOGAPP_TEST_PG_CONNECTION` env veya test çıktısındaki `appsettings.Development.json`'dan okunur (sır koda girmez, log'a yazılmaz). Fixture dispose'ta DB düşürülür (doğrulandı: kalan tek DB `blogdb_dev`). |
| `Messaging/Outbox/AgentRabbitMqOutboxCollection.cs` | Koleksiyon: DB fixture paylaşımı + broker testleriyle serileştirme. |
| `Messaging/Outbox/AgentAcceptanceServiceTests.cs` | 12 test: oturum yoksa unauthorized; misafir kabul (+ misafir kapalıysa forbidden); yayımlanmış makale snapshot'ı + content hash (D008); taslak makale forbidden (hiç kayıt yok); idempotency replay (yeni satır YOK) ve farklı payload çakışması; turn_sequence 1→2; yabancı konuşma forbidden; limit; outbox zarfı B1 doğrulayıcısından geçer; deadline backend tarafından mod bazlı set edilir. |
| `Messaging/Outbox/AgentOutboxRelayTests.cs` | 6 test — 4 kabul senaryosu dahil (aşağıda §3). |
| `Messaging/Broker/AgentRabbitMqBrokerTests.cs` | Yalnız `[Collection("agent-rabbitmq-outbox")]` eklendi (B2/B3 broker testlerinin kuyruk erişim yarışını önler); davranış değişikliği yok. |

## 2. B3 yerel kararları (plan metniyle eşleşme)

1. **`OwnerKey` sentetik sütun** (`"u:{guid}"` / `"g:{sessionId}"`): Postgres unique index'te NULL-distinct davranışı nedeniyle `(OwnerUserId, IdempotencyKey)` benzersizliği misafir satırlarını tekilleştirmezdi; tek sütun hem idempotency hem limit sorgusunu taşır.
2. **`article_revision` üretilMEDİ** (D008/L004): revizyon üretimi B8 kararıdır; B3 payload'ı makale referansı üçlüsü yerine `context_snapshot_reference` taşır (sözleşme kuralı: üçlüden herhangi biri varken üçü birden zorunlu — üçü de yok, doğrulayıcı kabul eder). Snapshot'ta `article_content_hash` (Content UTF-8 SHA-256) zaten var; B8 üçlüyü payload'a eklediğinde snapshot laşıma hazır.
3. **`AgentRunStatus` tek değerli (`Accepted`)**: kabul durumu ile Python `agent.run.accepted` olayı ayrı anlamlar (satır 305); projection (B5) enum'ı genişletecek.
4. **Outbox'a `DeadLettered` durumu eklendi**: plan sınırsız tekrarı yasaklar (main prompt kritik kontrol); `MaxAttempts` (varsayılan 12) aşıldığında kayıt operatöre bırakılır, ölçülür.
5. **Relay somut `RabbitMqAgentPublisher` tipine bağlandı**: B2'nin `IAgentBrokerPublisher` arayüzü `StartAsync` içermiyor (yaşam döngüsü yöntemi somut sınıfta) — donuk B2 dosyasına dokunulmadı, DI'da somut kayıt + arayüz yönlendirmesi yapıldı. **B2'de raporlanacak küçük arayüz eksisi.**
6. **Kuyruk test serileştirme**: B2 broker testleri + B3 relay testleri tek xunit koleksiyonunda; kuyruğa iki koleksiyondan eşzamanlı BasicGet yarışını önler.

## 3. Gerçek test kanıtları

Ortam: RabbitMQ 4.2 (`blogapp-rabbitmq`, healthy), PostgreSQL 18 (`blogapp-postgres`, healthy — compose'dan kaldırıldı), dotnet 10.0.400.

```
dotnet test src/backend/Presentation/Api.Tests --nologo -v q --filter "FullyQualifiedName~AgentAcceptanceServiceTests"
→ Başarılı! 12/12 (gerçek Postgres)

dotnet test src/backend/Presentation/Api.Tests --nologo -v q --filter "FullyQualifiedName~AgentOutboxRelayTests"
→ Başarılı! 6/6 × 3 koşu (gerçek Postgres + gerçek RabbitMQ; sınıf tekrarıyla flake doğrulaması)

GATE (düzeltme sonrası iki tam koşu):
dotnet test src/backend/Presentation/Api.Tests --nologo -v q
→ Başarılı! - Başarısız: 0, Başarılı: 90, Atlanan: 0, Toplam: 90, Süre: 3 m 16 s
→ Başarılı! - Başarısız: 0, Başarılı: 90, Atlanan: 0, Toplam: 90, Süre: 2 m 2 s
```

### Confirm-loss test sağlamlaştırması (ilk gate koşusunda 1 flake)

İlk tam gate koşularından birinde `ConfirmLoss_RedeliversOnlyWithSameMessageId` başarısız oldu; kök nedeni iki katmanlı:

1. **Test tasarımı:** confirm, test ayarındaki `ConfirmTimeout`'u (eski değer 5 sn) aşarsa relay yayını başarısız sayıp kaydı beklemede bırakır — ancak **geç gelen confirm'in mesajı kuyruğa düşmüş olur** (karanlık bölge; plan satır 301'in kastettiği durum). Lease sonrası ikinci deneme ikinci kopyayı üretir; testin `.Single(...)` tek kopya varsayımı bu MEŞRU davranışta kırılırdı. Düzeltme: test artık tüm kopyaları `CollectQueueUntilAsync` ile toplar ve asıl ölçütü doğrular — her kopyada **aynı message_id**, `delivery_attempt` dizisi **monoton artan** (0,1,…; atlama yok), routing key korunur. Test relay ayarları sağlamlaştırıldı (`ClaimLeaseSeconds` 60→10, `ConfirmTimeoutSeconds` 5→15). Üretim kodunda değişiklik gerekmedi; davranış tasarım gereğidir.
2. **Ortam:** aşağıdaki F3'teki dış broker yeniden başlatmaları koşu içi broker kesintileri de üretebilir; ikinci tam gate koşusundaki 12 hata bu olayla aynı anda yaşandı (`docker inspect` kanıtı).

### Gate senaryoları → test eşlemesi (hepsi gerçek broker+postgres)

1. **DB commit sonrası broker kapansa iş kaybolmaz** — `BrokerOutage_AfterDbCommit_WorkNotLost_ThenPublished`: `rabbitmqctl stop_app` ile gerçek broker kesintisi; broker KAPALIYKEN kabul başarılı, `agent_runs` + `outbox_messages` satırları duruyor (outbox `Pending`); `start_app` sonrası relay kaydı yayınlar, `agent.execute.q`'da aynı `message_id` ile mesaj doğrulanır.
2. **Confirm kaybı yalnız tekrar teslim üretir** — `ConfirmLoss_RedeliversOnlyWithSameMessageId`: ilk yayın confirm'lu (`Published`, ilk teslimat `delivery_attempt=0`); kayıt "lease'i dolmuş Claimed" olarak işaretlenir (confirm kaybı karanlık bölgesi); relay AYNI `message_id` ile tekrar yayınlar ve toplanan her kopyada `delivery_attempt` monoton artar (0,1,…; atlama yok), routing key korunur. Test, confirm'in `ConfirmTimeout`'u aşması halinde (tam suite yükünde görüldü: geç gelen confirm'in mesajı kuyruğa düşer, relay tekrar teslim eder — plan satır 301'in kastettiği karanlık bölge davranışı) tam kopya sayısı varsayımı yapmaz; message_id korunumunu + artan transport sayaç dizisini doğrular (consumer tarafı inbox tekilleştirmesi B4 kapsamıdır). İlk teslimde tek kopya senaryosunda kopya sayısı = deneme sayısıdır.
3. **Rollback durumunda hayalet komut oluşmaz** — `TransactionWithoutCommit_PersistsNoRunAndNoCommand` (commit'siz transaction → 0 satır) + `Accept_LosingUniqueTurnRace_RollsBackGhostCommand`: gerçek DB istisnası yolu — öteki transaction `(ConversationId, TurnSequence=1)`'i commit etmeden tutar; handler aynı turu hesaplayıp unique index'te kilit beklemeye geçer (pg_stat_activity poll ile deterministik tespit); kazanan commit edince handler `DbUpdateException` alır → ROLLBACK → `agent_runs`=1 (yalnız kazanan), `outbox_messages`=0.
4. **Aynı kaydı iki publisher alamaz** — `ClaimBatch_ConcurrentPublishers_GetDisjointRecords`: iki `OutboxClaimStore`, 8 bekleyen kayıt, eşzamanlı claim → kümeler ayrık, toplam 8, DB'de 8 `Claimed`.

Ek: `Relay_PublishesPendingRecord_WithConfirmAndAmqpProperties` — kuyruğa düşen mesajda routing key, AMQP `type`, `delivery_attempt=0` ve zarfın B1 sözleşme doğrulayıcısından geçtiği kuyrukta doğrulandı.

## 4. Bulgular, engeller ve ortam olayları

| # | Tür | Açıklama |
| --- | --- | --- |
| F1 | Engeller — RAG | `node docs/ai-agent-plan/source/tools/search.cjs verify` ve B3 sorgusu **çalıştırıldı ve HATA döndürdü: "Hata: manifest JSON ve YAML aynaları farklı."** `git status` temiz — uyumsuzluk COMMIT EDİLMİŞ arşiv durumunda; kaynak arşivi sahipliğim dışında. B3 teknik CONTEXT'i arşivden ALINAMADI; teknik iddialar plan metni + repo kodu + bu rapordaki gerçek test kanıtlarıyla desteklenmiştir. Metadata sahibinin `rebuild-metadata.cjs` çalıştırması gerekir. |
| F2 | B2 arayüz eksisi | `IAgentBrokerPublisher.StartAsync` içermiyor (yöntem somut sınıfta). Donuk dosyaya dokunulmadı; relay somut tipi kullanıyor. B2 sahibinin arayüze eklemesi önerilir. |
| F3 | Ortam olayı | Test koşuları SIRASINDA broker container'ı en az iki kez DIŞARI DAN yeniden başlatıldı: (a) ilk oturumda `blogapp-postgres` + `blogapp-rabbitmq` `Exited (137)` bulundu; (b) düzeltme sonrası ikinci gate koşusunda `docker inspect blogapp-rabbitmq` → `StartedAt=2026-10-11T21:52:50Z, ExitCode=0, RestartCount=0` (temiz stop/start — crash/OOM değil) ve aynı koşuda 12 broker testi zaman aşımıyla düştü. Benim testlerim postgres'i hiç durdurmaz; rabbitmq'da yalnız `rabbitmqctl stop_app/start_app` kullanılır (container yaşam döngüsüne dokunulmaz). Konteynerler compose ile yeniden kaldırıldı, healthy doğrulandı, gate 90/90 iki kez tekrarlandı. Kaynak: kullanıcı paralel çalışması/sistem olayı olabilir (L006 bağlamı); koşu öncesi broker/postgres healthy kontrolü önerilir. |
| F4 | Paralel çalışma | Koşu sonrası `git status`: `src/services/ai-agent-service/**` altında (Python, B4 sahipliği) değişiklikler ve yeni dosyalar var — bu teslimin kapsamı DIŞINDA; hiç dokunulmadı. |
| F5 | Kapsam dışına not | Relay, publisher hazır değilken her poll döngüsünde tek satır WARNING loglar (broker uzun süre kapalıysa aralıklı uyarı akışı); davranışsal sorun değil, B11 gözlemlenebilirlik incelemesinde sessizleştirilebilir. |
| F6 | Mevcut risk (B0'dan) | `appsettings.Development.json` içinde gerçek görünümlü DB parolası duruyor (B0 bulgusu); test fixture'ı bu dosyayı konfigürasyon yoluyla okur, değeri hiçbir çıktıya yazmaz. Temizlik/rotasyon kullanıcı kararıdır. |

## 5. B10 için entegrasyon notları

```csharp
// Program.cs (B10 sahipliğinde):
builder.Services.AddRabbitMqAgentMessaging(builder.Configuration);   // B2 (mevcut)
builder.Services.AddAgentOutbox(builder.Configuration);              // B3
// K3: açılışta topology declarer'ı çağrılmalı:
//   await initializer.InitializeAsync(...);  // AgentTopologyInitializer (B2 singleton)
```

- REST endpoint kabulü `AcceptAgentRunCommandRequest` + MediatR üzerinden; misafir için sunucu tarafı oturum kimliği (HttpOnly cookie, K5) üretip `GuestSessionId`'ye taşır.
- `appsettings`: `AgentAcceptance` ve `AgentOutbox` section'ları (varsayılanlar kodda mevcut; config opsiyonel).
- Production'da migration'lar mevcut `RunMigrationsOnStartup` akışıyla uygulanır; bu teslim DEV veritabanına migration uygulamadı (yalnız izole `blogdb_b3tests`'e; fixture sonrasında düşürülür).

## 6. Çalıştırılmayan / kapsam dışı kontroller

- Migration production/`blogdb_dev` veritabanına uygulanmadı (dağıtım kararı B10/deploy'a ait).
- `outbox.age_seconds`/`outbox.attempts` ölçümleri kodda mevcut; /metrics paneli üzerinden doğrulama yapılmadı (B11 gözlemlenebilirlik kapsamı).
- Python/B4 inbox tekilleştirmesi ile uçtan uca senaryo (run → execute.q → intake ACK) B4'ün kapısıdır; B3 yalnız backend tarafını kanıtlar.
- RAG kaynak arşivi hata durumunda (F1) — arşivden CONTEXT alınamadı.
