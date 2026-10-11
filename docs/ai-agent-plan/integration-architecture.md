# Backend–Agent entegrasyon mimarisi ve sahiplik kararları (B0 çıktısı)

Bu belge B0 aşamasının mimari çıktısıdır: mevcut .NET altyapısı kodla doğrulanarak, RabbitMQ
üzerinden Python agent haberleşmesi için servisler arası mimari, sözleşme/DTO konumları ve
sahiplik kararları kaydedilir. Hiçbir kod dosyası bu aşamada değiştirilmedi; buradaki konumlar
**öneridir** ve ilgili aşamada (B1–B5) uygulanır.

- Kaynak plan: `docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md` ("Aşama B0", "Ortak RabbitMQ geliştirme promptu").
- Kaynak arşiv CONTEXT'i: [ENG-OUTBOX#C1], [ENG-OUTBOX#C2], [RMQ-DOTNET#C1], [RMQ-DOTNET#C2], [PG-ISOLATION#C1], [AIO-PIKA#C1], [AIO-PIKA#C2], [RMQ-RELIABILITY#C1], [FASTAPI-LIFESPAN#C1], [FASTAPI-LIFESPAN#C2] (`node docs/ai-agent-plan/source/tools/search.cjs verify` → valid, 30 kaynak / 60 parça; 2026-10-11).
- Kanıt yöntemi: tüm mevcut-kod iddiaları bu checkout'ta okunan dosya/satır referanslıdır; kaldırılmış altyapıya dair iddialar `git show 3dbdef8` çıktısıyla belgelenmiştir.

## 1. Doğrulanmış mevcut durum (çalışma ağacı, 8f148ab + feature/ai-agent-integration)

| Alan | Durum | Kanıt |
| --- | --- | --- |
| Hosting | ASP.NET Core 10 minimal API, Kestrel, `net10.0` | `src/backend/Presentation/API/Program.cs:14-58`, `src/backend/Presentation/API/API.csproj:4` |
| Persistence | EF Core 10.0.1 + Npgsql 10.0.0, `EnableRetryOnFailure(3)`, migration'lar Infrastructure assembly'de | `src/backend/Infrastructure/Infrastructure/DependencyInjection.cs:50-60` |
| Authentication | JWT Bearer; token Authorization header veya `accessToken` cookie'sinden; jti blacklist + kullanıcı geneli invalidation | `src/backend/Presentation/API/Extensions/AuthenticationExtensions.cs:26-64` |
| SignalR | Tek hub: `PublicCacheHub` (AllowAnonymous, grup whitelist `posts/categories/tags`); IP başına bağlantı limiti middleware'i | `src/backend/Presentation/API/Program.cs:108`, `src/backend/Presentation/API/Hubs/PublicCacheHub.cs:8`, `src/backend/Presentation/API/Middlewares/SignalRConnectionLimitMiddleware.cs:43-85` |
| Background service'ler | 2 adet: `RefreshTokenCleanupService`, `IdempotencyCleanupService` (6 saat aralık, retention bazlı `ExecuteDeleteAsync`) | `src/backend/Infrastructure/Infrastructure/DependencyInjection.cs:104-105`, `src/backend/Infrastructure/Infrastructure/Services/IdempotencyCleanupService.cs:10-73` |
| Outbox/Inbox | **Çalışma ağacında yok.** `grep -ril "rabbitmq|masstransit|outbox|inbox"` backend kaynak ağacında boş döndü. NuGet referanslarında RabbitMQ paketi yok | Bu ask içinde çalıştırılan grep; `grep -h PackageReference src/backend/*/*/*.csproj` çıktısı |
| En yakın mevcut yapı | `IdempotencyRecord` (Processing/Completed/Failed durum makinesi, correlation/causation alanları, Postgres unique-violation yarış çözümü) | `src/backend/Core/Domain/Entities/IdempotencyRecord.cs:6-25`, `src/backend/Infrastructure/Infrastructure/Services/IdempotencyService.cs:56-82` |
| Transaction altyapısı | `IUnitOfWork.BeginTransactionAsync(IsolationLevel)` + `ExecuteResilientAsync` (EF execution strategy) — outbox transaction'ı için hazır | `src/backend/Infrastructure/Infrastructure/Persistence/Repositories/UnitOfWork.cs:79-122` |
| Docker | Local: postgres 18 + redis 8 + backend + frontend (`backend-net`/`frontend-net` ayrı). Prod: + nginx, bellek limitleri, InternalHosts. **Her iki compose'da da RabbitMQ servisi yok** | `docker/docker-compose.yml:8-152`, `deploy/docker-compose.prod.yml` |
| Python/agent kodu | Çalışma ağacında hiç Python dosyası yok (`find . -name "*.py"` boş) | Bu ask içinde çalıştırılan find |

### Kaldırılmış önceki messaging altyapısı (varsayım değil, git kanıtı)

Commit `3dbdef8` ("feat: major refactor — remove AI agent service, consolidate migrations, add
features") şu bileşenleri bilinçli kaldırmıştır (`git show --stat 3dbdef8`):

- `BlogApp.BuildingBlocks.Messaging`: `RabbitMqConnection.cs` (singleton bağlantı, `SemaphoreSlim` kilidi, `AutomaticRecoveryEnabled`, 30 s heartbeat, `ClientProvidedName`), `RabbitMqEventBus.cs`, `RabbitMqEventConsumer.cs`, `IEventBus`/`IEventHandler`/`IIntegrationEvent`, `RabbitMqSettings`.
- Outbox/inbox: `OutboxMessage` + `ConsumerInboxMessage` entity'leri, `OutboxService` (status claim mekanizması `ExecuteUpdateAsync` ile, attempt sayacı, üst sınırı 30 s olan backoff), `OutboxPublisherHostedService`, `NoOpOutboxService`, `20260309002227_CreateOutboxMessagesTable` migration'ı.
- AI agent service (Python) ve onun uçları: `AiEndpoints`, `ChatEndpoints`, `docker/ai-agent-service/Dockerfile`.
- Agent'a dönük SignalR hub'ları: `ChatEventsHub` (session claim doğrulaması + `chat_{sessionId}` grup adı) ve `RateLimitedHubBase` (bağlantı başına invocation limiti).

**B0 sonucu:** Sıfırdan tasarım yok; kaldırılan modülün şekli (bağlantı ömrü, outbox claim/backoff,
inbox durumu, session-claim'li hub) B2+ için geri kazanılabilir bir referanstır. Ancak eski kod
RabbitMQ.Client eski major API'siyle yazılmıştır; [RMQ-DOTNET#C1] ve [RMQ-DOTNET#C2] uyarınca
client 7.x API'leri (bağlantı kanalı ömrü, `ReadOnlyMemory` payload) doğrulanarak yeniden
yazılacaktır — eski dosyalar olduğu gibi geri getirilmez.

## 2. Servisler arası mimari (hedef akış ve adım sahipleri)

Planın akışı (`02-rabbitmq-haberlesme-plani.md` "Servisler arası mimari" diyagramı) korunur.
"İstekten sonuç gösterimine kadar" her adımın sahibi:

| # | Adım | Sahip | Karar gerekçesi (kanıt) |
| --- | --- | --- | --- |
| 1 | Kullanıcı isteğinin alınması ve doğrulanması | .NET Presentation — yeni `AgentEndpoints` (JWT zorunlu; rate limit `IpRateLimiting` genel kurallarına eklenir) | Mevcut endpoint deseni: `RegisterEndpointsExtensions.cs:6-19`; istemciden gelen `owner_id` yetki kaynağı değildir (ortak prompt kuralı, plan satır 124) |
| 2 | run_id üretimi, iş kabulü, outbox kaydı — tek DB transaction'ı | .NET Application (MediatR command) + Infrastructure (outbox), `IUnitOfWork` transaction'ı içinde | Plan satır 10; transaction altyapısı hazır: `UnitOfWork.cs:79-122` |
| 3 | `run_id` + kabul durumu dönüşü (202) | .NET Presentation | Mevcut deseni: `IdempotencyHelper.BuildProcessingAccepted` (`Helpers/IdempotencyHelper.cs:65-75`) |
| 4 | Outbox → broker yayını (publisher confirm) | .NET Infrastructure outbox publisher (hosted service) | [ENG-OUTBOX#C1] (mesaj, iş verisiyle aynı transaction'da; ayrı relay yayınlar); kaldırılan `OutboxPublisherHostedService` şekli referans |
| 5 | Komutun intake tarafından kalıcı inbox/job'a yazılıp ACK'lenmesi | Python intake consumer (agent repo) | Plan satır 12; [AIO-PIKA#C1] async client; ACK yalnız commit sonrası (plan satır 87) |
| 6 | İşin lease ile alınıp agent çekirdeği (LangGraph) yürütülmesi | Python worker (agent repo); agent çekirdeği envelope görmez | Plan satır 13 ve 38; D001/D002 kararları |
| 7 | Sonuç/ilerleme olaylarının agent outbox'ına yazılıp yayınlanması | Python worker + agent outbox relay | Plan satır 14; [AIO-PIKA#C2] publisher confirm broker kabulünü gösterir, iş bitişini değil (plan satır 16) |
| 8 | Olayların backend tarafından inbox + projection'a yazılması, ACK | .NET Infrastructure event consumer (hosted service) | Plan satır 15; scope-per-cycle deseni mevcut: `IdempotencyCleanupService.cs:49-73` |
| 9 | Sonucun tarayıcıya canlı iletimi | .NET Presentation — yeni run hub'ı (`IHubContext` broadcast; grup adı `agent-run:{runId}`) | Mevcut broadcast deseni: `CacheInvalidationNotifier` (`Presentation/API/Services/CacheInvalidationNotifier.cs:26-39`) |
| 10 | Arayüzde sonuç/ilerleme gösterimi | Next.js client — yeni hook (bağlantı, otomatik yeniden bağlanma, grup aboneliği) | Mevcut referans desen: `src/frontend/blogapp-web/src/hooks/use-cache-sync.ts:46-127` |

**Ayırma kuralı (kabul ölçütü 2):** Agent algoritmaları (router, retrieval, araştırma — A planı)
yalnız Python worker içinde yaşar ve `ExecutionContext` girdisi / `AgentOutcome`+`DomainProgress`
çıktısı ile konuşur (ortak prompt, plan satır 99). .NET tarafı agent davranışı içermez; yalnız
kabul, taşıma, projection ve gösterim sorumluluğu taşır. Broker envelope'u yalnız adaptör
katmanlarında bilinir.

## 3. Sahiplik kararları (B0 karar listesi)

### K1 — Backend ve Python migration sahipliği

- Backend şeması EF Core ile Infrastructure assembly'den yönetilir; mevcut tek-konsolide-migration politikası korunur (`dotnet ef` komutları `src/backend/CLAUDE.md:20-32`; `20260407130831_InitialCreate`). Prod'da `Database:RunMigrationsOnStartup=true` ile uygulama açılışında çalışır (`Program.cs:111-128`).
- Backend EF migration'ları **agent tablolarına asla dokunmaz**. Python tarafı kendi tablolarının tek sahibidir; plan bu ayrımı açıkça kurar (`02-rabbitmq-haberlesme-plani.md` satır 38: "tabloların sahibi ve migration sorumluluğu ayrıdır").
- İki taraf aynı PostgreSQL sunucusunu paylaşabilir; öneri: agent kendi schema'sında (örn. `agent`) ayrı DB rolüyle çalışır, schema'lar arası foreign key kurulmaz — servis sınırı broker sözleşmesidir.
- **Açık kalem:** Python migration aracı seçimi (Alembic adayı) B0 kaynak arşivinde karşılıksızdır (`search.cjs --stage B0` sorguları migration aracına dair parça döndürmedi). Bu, "Bu konuda elimde yeterli bilgi yok" kapsamındadır; araç seçimi ve doğrulaması B2+'a, A tarafı repo yapısıyla birlikte bırakılır.

### K2 — Komut, kontrol, içerik ve olay consumer konumları

| Kuyruk (plan topolojisi) | Consumer | Konum |
| --- | --- | --- |
| `agent.execute.q` | Python intake (komut) | Agent repo (A1 W1'de oluşur) — B0'da yok |
| `agent.control.q` (cancel/resume/action result) | Python kontrol consumer | Agent repo — B0'da yok |
| `agent.content.q` (article/profile sync) | Python içerik indeksleyici | Agent repo — B0'da yok |
| `backend.agent.events.q` | **.NET backend event consumer** | `src/backend/Infrastructure/Infrastructure/Messaging/` (önerilen; hosted service, `AddHostedService` ile `DependencyInjection.cs:104-105` deseninde kaydedilir) |

Tek .NET consumer yeterlidir: olay consumer'ı inbox + projection'ı aynı transaction'da yazar;
SignalR broadcast'i projection commit'inden **sonra** yapar.

### K3 — Broker topology yönetimi

- **Tek açıklayıcı (declarer): backend.** Yeni bir Infrastructure hosted service (topology initializer) açılışta tüm durable exchange/kuyruk/binding/DLQ'ları idempotent declare eder. Gerekçe: main prompt "broker topology için tek entegrasyon sahibi belirle" kuralı; çift taraflı declare'da args uyuşmazlığı `PRECONDITION_FAILED` üretir.
- Python tarafı startup'ta kuyruk/exchange varlığını pasif kontrol ile doğrular, uyuşmazlıkta fail-fast eder (sessiz yeniden tanımlama yok).
- Exchange türleri ve routing eşlemeleri B1 planındaki tablodan alınır (`blog.agent.commands`, `blog.agent.events`, `blog.content.events`; `agent.execute.requested.v1` vb.). Topology kurulumunun kendisi B2 kapsamındadır; B0'da kod yazılmadı.

### K4 — İş kabulü, yürütme ve sonuç gösterimi sahipleri

Bölüm 2 tablosunun özeti: **kabul = .NET backend** (transaction'lı run + outbox), **yürütme =
Python** (intake → job → worker, lease ile), **sonuç gösterimi = .NET backend projection +
SignalR + Next.js client**. Arada tek veri yolu broker sözleşmeleridir; hiçbir taraf diğerinin
veritabanına yazmaz.

### K5 — Misafir oturum ve kullanıcı oturumu

- **Kullanıcı oturumu:** mevcut JWT altyapısı kaynaktır — access token header veya `accessToken` cookie'sinden alınır, jti blacklist ve kullanıcı geneli invalidation denetlenir (`AuthenticationExtensions.cs:31-63`). Kullanıcıya ait run kaydında sahip `UserId` claim'inden **backend** tarafından yazılır; istemcinin gönderdiği owner alanı yetki kaynağı değildir (ortak prompt kuralı, plan satır 124).
- **Misafir oturumu:** bugün kalıcı misafir kimliği yok; `IdempotencyRecord.SessionId` alanı üretimde hiç doldurulmuyor (`IdempotencyBehavior.cs:95`: `SessionId: null`) ve `PublicCacheHub` tamamen anonim (`Program.cs:108`). Karar: misafir run için backend, run kabulünde sunucu tarafı misafir oturum kimliği (rastgele, HttpOnly cookie) üretir ve run sahibi olarak kaydeder. Canlı takip grubuna (`agent-run:{runId}`) katılım yalnız sahibi olan kimlikle açılır — bu denetim deseni kaldırılan `ChatEventsHub`'daki session-claim doğrulamasıyla eşdeğerdir (`git show 3dbdef8^:.../Hubs/ChatEventsHub.cs`). Misafir kotası, kullanıcı kotasından sıkı IP rate limit ile ayrışır (`IpRateLimiting` mevcut altyapı).
- **Ürüne açık kalem:** misafirlere agent erişimi verilip verilmeyeceği ve kota oranları ürün kararıdır; B0 teknik sınırı (kimlik backend'de doğrulanır, grup katılımı run sahibine kilitli) iki durumda da geçerlidir.

### K6 — Lease, deadline ve event sırası

- **Lease/fencing sahibi: Python.** Job tablosunda `lease_owner`, `lease_expires_at`, `execution_attempt`/`fencing_token`; eski worker'ın sonucu ezemez (main prompt kritik kontrol; uygulama B5). Backend lease tutmaz.
- **Deadline sahibi: backend.** `deadline_at` kabul anında backend tarafından, mod bütçe politikasına göre üretilip envelope'a yazılır (B1 alan tablosu, plan satır 193). Bütçe değerlerinin politikası A2 sahipliğindedir; B1 yalnız taşımayı tanımlar.
- **Event sırası:** Python, run başına monoton `event_sequence` üretir; `execution_attempt` transport tekrarından ayrı alandır (plan satır 237). Backend projection, terminal durmdan sonra gelen düşük/eşit sequence'li olayları uygular. Sıra garantisi broker'dan değil, projection'daki sequence korumasından gelir; broker tekrar teslimi normal karşılanır ([RMQ-RELIABILITY#C1]: dedup/idempotency uygulama sorumluluğudur).

### K7 — Mesaj ve sonuç boyut sınırları

- Mevcut HTTP sınırı referansı: Kestrel gövde 50 MB, form değeri 4 MB — config-bağlı `ServerLimitsSettings` (`ServerLimitsSettings.cs:11-16`). Broker mesaj sınırı **ayrı ve çok daha küçük** tutulur.
- **Karar:** Komut/olay envelope payload üst sınırı config ile bağlanır (`AgentMessaging:MaxPayloadBytes`, önerilen başlangıç 256 KiB; B1'de sabitlenir). Makale içeriği komuta gömülmez: execution isteği makale **revizyonu/hash referansı** ve doğrulanmış bağlam snapshot referansı taşır (plan satır 235); büyük içerik/raporlar DB'de kalır, mesaj referans taşır. Sonuç raporları için ayrı, daha geniş ama yine sınırlı bir sonuç üst sınırı tanımlanır (B1).
- Publisher, sınırı aşan payload'ı reddeder (outbox kaydı failed + metri); consumer tarafında da aynı üst sınır doğrulanır. Broker çerçeve/limit davranışı B2'de kurulu broker sürümü belgesiyle doğrulanacaktır (B0 CONTEXT'inde broker mesaj boyut limiti yoktur; uydurulmadı).

### K8 — Yerel ve üretim kurulum farkları

| Konu | Yerel (`docker/docker-compose.yml`) | Üretim (`deploy/docker-compose.prod.yml`) |
| --- | --- | --- |
| RabbitMQ | `backend-net` ağına tek broker servisi eklenecek; portlar `127.0.0.1`'e bound (postgres/redis deseni, satır 16/36). `frontend-net`'e **eklenmez** — broker kimlik bilgisi tarayıcıya ulaşmaz (plan satır 9) | Aynı servisin prod compose'a eklenmesi + ayrı volume; quorum queue ve düğüm sayısı B11'de değerlendirilir (plan satır 60: tek düğüm HA sağlamaz) |
| Migration | Manuel (`RunMigrationsOnStartup` dev'de false, `Program.cs:114`) | Uygulama açılışında otomatik (prod compose `Database__RunMigrationsOnStartup: "true"`) |
| Kimlik/secret | `.env` zorunlu alanlar (`:?` sentaksı, compose satır 12-13) | Env-only secret'lar; `SSL Mode=Require` DB örneği (`appsettings.Production.Example.json`) |
| Gözlemlenebilirlik | `/health`, `/metrics` localhost | `InternalHosts` kısıtı (prod compose `InternalHosts__0..2`) |
| Risk notu | — | Prod compose'da api konteyneri `mem_limit: 300m`; consumer + publisher eklendiğinde bu sınır B11 kapasite incelemesinde yeniden ölçülmelidir |

## 4. Önerilen sözleşme/DTO ve modül konumları (B1 uygulayacak)

### .NET tarafı (mevcut Clean Architecture katmanları korunur)

| Konum (öneri) | İçerik | Aşama |
| --- | --- | --- |
| `docs/ai-agent-plan/contracts/` | Sürümlenmiş JSON Schema dosyaları — **tek sözleşme kaynağı**; .NET ve Python bundan türetir/doğrular | B1 |
| `src/backend/Core/Application/Common/Interfaces/Messaging/` | `IOutboxService`, `IAgentCommandPublisher`, `IAgentEventConsumer` soyutlamaları | B1/B3 |
| `src/backend/Core/Application/Common/Options/AgentMessagingSettings.cs` | Broker bağlantı, payload üst sınırı, deadline varsayılanları (`ServerLimitsSettings` deseni) | B1/B2 |
| `src/backend/Core/Domain/Entities/` | `AgentRun`, `OutboxMessage`, `AgentEventInbox` (`IdempotencyRecord` durum makinesi + kaldırılan `OutboxMessage`/`ConsumerInboxMessage` şekillerinin birleşimi) | B3/B4 |
| `src/backend/BuildingBlocks/BuildingBlocks/Messaging/` | RabbitMQ bağlantı ömrü, publisher (confirm'lu), consumer tabanı, topology initializer — kaldırılan `BlogApp.BuildingBlocks.Messaging` modülünün 7.x client ile yeniden yazımı | B2 |
| `src/backend/Infrastructure/Infrastructure/Messaging/` | Outbox publisher hosted service, backend event consumer hosted service | B3/B4 |
| `src/backend/Presentation/API/Endpoints/AgentEndpoints.cs` + `Hubs/AgentRunsHub.cs` | Kabul uçları + canlı takip hub'ı | B4/B9-B10 |
| `tests/BlogApp.Presentation.Api.Tests/` | Sözleşme ve akış testleri (mevcut test projesi, net10.0) | B1+ |

Envelope alanları (message_id, message_type, schema_version, run_id, conversation_id,
correlation_id, causation_id, occurred_at, deadline_at, producer, trace_context, payload) B1
planındaki tabloyla birebir alınır; AMQP `message_id`/`correlation_id`/`content_type` header'ları
envelope ile tutarlı set edilir (plan satır 233). `IdempotencyRecord`'daki correlation/causation
alanları (`IdempotencyRecord.cs:11-12`) mevcut istek zinciriyle aynı isimlendirme geleneğini
sürdürür.

### Python tarafı

- Gerçek agent deposu henüz yok (A1 W1). **Öneri:** agent projesinde `app/messaging/contracts/`
  (envelope + mesaj Pydantic modelleri) ve `schemas/` (JSON Schema kopyaları/konfeti). Kesin
  konum A1 repo iskeletiyle sabitlenecek; B1, A1 iş modelleri hazır olduktan sonra onlara
  eşlenir (main prompt W1: "Önce agent iş modelleri; ardından sürümlenmiş mesaj sözleşmeleri").
- Python consumer'ların yaşam döngüsü FastAPI lifespan içinde kurulur: yield öncesi bağlantı/
  consumer başlangıcı, yield sonrası temizlik [FASTAPI-LIFESPAN#C1]; startup/shutdown
  handler'larıyla karıştırılmaz [FASTAPI-LIFESPAN#C2].
- Consumer callback'inde payload bellek kuralı: client 7.x'te gövde `ReadOnlyMemory` olarak
  gelir, ACK sonrası kullanılacaksa callback içinde kopyalanır [RMQ-DOTNET#C2].

### Test executor kararı (gerçek agent yokken)

Henüz gerçek agent bulunmadığından (A1 W1'de gelecek; bu askın giriş noktası notu) B fazlarının
doğrulaması **sözleşmeye uyan test executor** ile yapılır:

1. **Konum:** .NET tarafı akış testleri için `tests/BlogApp.Presentation.Api.Tests/` altında test
   double publisher/consumer (main prompt izni: "Başka ekibin sözleşmesi hazır değilse tanımlanmış
   sınırla test double kullanılabilir"). Broker'a bağlanan uçtan uca test executor, Python tarafı
   oluştuğunda agent deposunun test klasöründe yaşar (konum A1 ile sabitlenecek).
2. **Gerçek olmayan yürütmenin işaretlenmesi (üç katman):**
   - Envelope `producer` alanı `"test-executor"` kimliğini taşır (B1 producer tanımı);
   - Sonuç payload'ı `execution_origin: "test_executor"` işareti taşır; projection bu işaretli
     sonuçları UI'da simülasyon olarak etiketler;
   - Test executor yalnız Development/Test ortamında bağlanabilir; Production'da etkin
     bulunan yapılandırma startup'ı fail-fast ile durdurur (main prompt kapısı: "Test
     sağlayıcısı üretimde etkinleştirilemez").
3. **Raporlama kuralı:** test double veya test executor başarısı gerçek model/broker entegrasyonu
   başarısayılmaz; progress kayıtlarında ara başarı olarak ayrı işaretlenir (main prompt satır
   95 ve 117).

## 5. B0 kapanışında açık kalemler (B1 girişine devir)

- Python migration aracı seçimi — kaynak arşivinde karşılık yok (K1).
- Python sözleşme modülünün kesin dizin yolu — A1 repo iskeleti bekliyor (Bölüm 4).
- Broker mesaj boyutu/çerçeve limitlerinin kurulu broker sürümü belgesiyle doğrulanması (K7).
- Misafir agent erişimi ve kota oranları — ürün kararı (K5).
- Prod `mem_limit` kapasite gözden geçirmesi — B11 (K8).
