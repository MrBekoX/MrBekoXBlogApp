# B0 Faz Raporu — Entegrasyon sınırı ve mevcut altyapı incelemesi

- **Tarih:** 2026-10-11
- **Rol:** Bağımsız B0 faz uzmanı (mesajlaşma mimarisi denetçisi)
- **Base:** `origin/main` = 8f148ab, branch `feature/ai-agent-integration`, çalışma ağacı temiz (izlenmeyen: `.video_agent/`, `.zcode/`, `.zcodeignore`)
- **Kapsam:** Salt okunur denetim. Hiçbir kod dosyası değiştirilmedi; RabbitMQ paketi/topology kurulmadı (B2+). `progress.md` ve `decisions.md` dokunulmadı.
- **Çıktı dosyaları:** `docs/ai-agent-plan/phase-reports/B0-rapor.md` (bu dosya), `docs/ai-agent-plan/integration-architecture.md` (mimari + sahiplik kararları K1–K8).

## 1. Yapılan iş

Planın B0 bölümü (`docs/ai-agent-plan/02-rabbitmq-haberlesme-plani.md:142-167`) ve "Ortak
RabbitMQ geliştirme promptu" (`:95-140`) satır satır uygulandı: backend hosting, persistence,
authentication, SignalR, background service'ler, outbox/inbox durumu ve Docker yapısı kodla
incelendi; planın sekiz karar kalemi `integration-architecture.md` K1–K8'de belgelendi.

## 2. Çalıştırılan kontroller (gerçek çıktılarla)

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| Kaynak arşivi doğrulama | `node docs/ai-agent-plan/source/tools/search.cjs verify` | `"valid": true, "sources": 30, "chunks": 60, "stages": 23` |
| B0 teknik CONTEXT | `node docs/ai-agent-plan/source/tools/search.cjs search --stage B0 --query "RabbitMQ backend Python istemcisi ve outbox mimarisi" --format prompt` | 6 parça döndü: ENG-OUTBOX#C1/C2, RMQ-DOTNET#C1, PG-ISOLATION#C1, AIO-PIKA#C1/C2 |
| B0 ek CONTEXT | `... search --stage B0 --query "FastAPI lifespan consumer startup shutdown ve Python migration yonetimi" --format json` | FASTAPI-LIFESPAN#C1/C2, RMQ-DOTNET#C2, RMQ-RELIABILITY#C1 eklendi; **Python migration aracına dair parça yok** |
| Messaging/outbox taraması | `grep -rn --include="*.cs" -ilE "rabbitmq|masstransit|outbox|inbox" src/backend/` (bin/obj hariç) | **Boş** — çalışma ağacında messaging altyapısı yok |
| Paket envanteri | `grep -h PackageReference src/backend/*/*/*.csproj` | RabbitMQ/MassTransit paketi yok; EF Core 10.0.1, Npgsql 10.0.0, MediatR 14.0.0, JwtBearer 10.0.1, StackExchange.Redis 2.10.1, OTel 1.15.x |
| Hosted service taraması | `grep -l "BackgroundService\|IHostedService"` | Yalnız `RefreshTokenCleanupService`, `IdempotencyCleanupService` |
| Kaldırılmış altyapı | `git log --all -i --grep=messaging` → `git show --stat 3dbdef8`; `git show 3dbdef8^:<dosya>` | `BlogApp.BuildingBlocks.Messaging` (RabbitMqConnection/EventBus/EventConsumer), `OutboxMessage`/`ConsumerInboxMessage` + `OutboxService` + `OutboxPublisherHostedService`, Python AI agent service, `ChatEventsHub`/`RateLimitedHubBase` kaldırılmış |
| Python varlığı | `find . -name "*.py"` (node_modules/.git hariç) | Boş |
| Build/test | — | **Çalıştırılmadı** — B0 salt okunur denetimdir; plan bu aşama için build/test kapısı içermez |

## 3. Bulgular

### F1 — Messaging altyapısı sıfırdan kurulacak, ancak tasarımsız değil (bilgi, severity: info)
Çalışma ağacında RabbitMQ/outbox/inbox kodu yok (Yukarıdaki grep kanıtı). Bununla birlikte commit
`3dbdef8` öncesinde tam bir hat vardı: singleton RabbitMQ bağlantısı (auto-recovery, 30 s
heartbeat), claim-mekanizmalı outbox publisher (`ExecuteUpdateAsync` ile status claim, attempt
sayacı, 30 s üst sınırlı backoff), `ConsumerInboxMessage` (Processing status, consumer_name +
operation_id anahtarı), session-claim'li `ChatEventsHub`. Bu şekiller B2+ için referans olarak
`integration-architecture.md` Bölüm 1'e işlendi; eski kod eski client major API'siyle yazıldığı
için [RMQ-DOTNET#C1]/[RMQ-DOTNET#C2] uyarısıyla 7.x API'lerine göre yeniden yazılacaktır.

### F2 — En yakın mevcut yapılar B3/B4'e doğrudan taşınabilir (bilgi, severity: info)
- `IdempotencyRecord` durum makinesi (Processing/Completed/Failed) + correlation/causation alanları
  + Postgres unique-violation yarış çözümü (`IdempotencyService.cs:56-82`) — agent event inbox ve
  run kaydı için isimlendirme/durum deseni.
- `UnitOfWork.BeginTransactionAsync(IsolationLevel)` + `ExecuteResilientAsync`
  (`UnitOfWork.cs:79-122`) — "iş kabulü ve outbox aynı transaction'da" gereksinimi için hazır.
  Dikkat: `EnableRetryOnFailure(3)` ile açık transaction kombinasyonu, outbox yazımı
  execution-strategy uyumlu sarmalanmalı (B3 implementasyon notu).
- `CacheInvalidationNotifier` (`IHubContext` + grup broadcast) ve frontend `use-cache-sync.ts`
  (otomatik yeniden bağlanma + grup yeniden aboneliği) — sonuç gösterimi hattının birebir deseni.

### F3 — Gerçek zamanlı kanal bugün yalnız cache invalidation (sınır, severity: info)
Tek hub `PublicCacheHub`, AllowAnonymous, grup whitelist'i `["posts", "categories", "tags"]`
(`PublicCacheHub.cs:8`); bağlantı başına IP limiti `SignalRConnectionLimitMiddleware.cs:43-85`.
Agent run ilerlemesi için yeni bir hub/endpoint seti gerekecek; sahiplik kararı K4/K5'te.

### F4 — Misafir oturumu diye kalıcı bir kimlik yok (boşluk, severity: medium)
`IdempotencyRecord.SessionId` alanı uygulama içinde hiç doldurulmuyor (`IdempotencyBehavior.cs:95`
`SessionId: null`); anonim ziyaretçi yalnız geçici SignalR connection'ı. Agent akışı misafir
run'ı destekleyecekse sunucu tarafı misafir oturum kimliği üretilmeli — karar K5. Ürün kararı
(misafir erişimi/kota) kullanıcıya açık bırakıldı.

### F5 — Prod kapasite ve konfigürasyon riskleri (risk, severity: low-medium)
- Prod compose'da api konteyneri `mem_limit: 300m` (`deploy/docker-compose.prod.yml`); consumer +
  publisher eklenince yeniden ölçülmeli (K8, B11).
- `src/backend/Presentation/API/appsettings.Development.json:13-14` içinde gerçek görünümlü dev
  DB/Redis parolaları repoya commit edilmiş durumda. Dev-only olsa da secret'ın repoda durmaması
  için Example dosyası + `.env` desenine taşınması önerilir (mevcut `appsettings.Development.Example.json`
  var). Bu dosya B0 izin listesinde olmadığından **değiştirilmedi**; düzeltme ilgili dosya
  sahibine bırakıldı.
- Prod compose RabbitMQ eklendiğinde broker servisinin `blogapp-network`'te backend ile sınırlı
  tutulması ve front'a açılmaması gerekir (plan satır 9).

### F6 — Planın öngördüğü giriş noktalarının durumu (doğrulama, severity: info)
Plan B0'ın "Agent planındaki giriş noktalarını doğrula" maddesi: **gerçek agent yok** (çalışma
ağacında Python dosyası yok; A1 W1'de gelecek). Karar: sözleşmeye uyan test executor üç katmanlı
işaretlemeyle kullanılacak — `integration-architecture.md` Bölüm 4 "Test executor kararı":
(1) envelope `producer: "test-executor"`, (2) sonuç payload'ında `execution_origin: "test_executor"`
ve UI'da simülasyon etiketi, (3) Production'da fail-fast. Test double başarısı gerçek broker/model
entegrasyonu sayılmaz (main prompt kuralları).

## 4. Karar listesi (özet — ayrıntı `integration-architecture.md`)

| Kimlik | Karar |
| --- | --- |
| K1 | Migration sahipliği: backend EF (Infrastructure assembly, tek konsolide migration politikası) kendi şemasında; Python kendi tablolarının tek sahibi; schema'lar arası FK yok. Python migration aracı seçimi B2+'a (arşivde kaynak yok) |
| K2 | Consumer konumları: execute/control/content Python'da (agent repo); `backend.agent.events.q` consumer'ı .NET Infrastructure hosted service |
| K3 | Topology: tek declarer backend topology initializer (idempotent, startup); Python pasif doğrulama + fail-fast. Kurulum B2 |
| K4 | Kabul = .NET (run + outbox tek transaction); yürütme = Python (intake→job→worker, lease); gösterim = .NET projection + SignalR + Next.js |
| K5 | Kullanıcı run sahipliği JWT claim'inden backend tarafından; misafir run sunucu üretimi misafir oturum kimliğiyle; `agent-run:{runId}` grup katılımı sahip kimliğine kilitli. Misafir kotası ürün kararı |
| K6 | Lease/fencing Python'da; `deadline_at` backend'de üretilir; event sırası Python üretimi monoton `event_sequence` + backend projection sequence koruması; transport tekrarı `execution_attempt`'ten ayrı |
| K7 | Payload üst sınırı config-bağlı (öneri 256 KiB, B1'de sabitlenir); içerik referans/hash ile taşınır, gömülmez; broker çerçeve limiti B2'de belgeyle doğrulanır |
| K8 | Local: broker yalnız `backend-net`'te, portlar localhost-bound; prod: ayrı volume + quorum değerlendirmesi B11; migration dev=manuel/prod=startup; prod `mem_limit` yeniden ölçülecek |

## 5. Kabul ölçütleri eşlemesi

| Ölçüt (plan satır 167) | Durum | Kanıt |
| --- | --- | --- |
| İstekten sonuç gösterimine kadar her adımın sahibi belli | **Karşılandı** | `integration-architecture.md` Bölüm 2 tablosu (10 adım, her biri kanıt referanslı) |
| Agent algoritmaları ile mesaj altyapısı ayrı | **Karşılandı** | Aynı belge Bölüm 2 ayırma kuralı: agent çekirdeği envelope görmez (plan satır 38, 99); .NET tarafı agent davranışı içermeyecek şekilde konumlandırıldı (Bölüm 4 tablosu) |
| B1 sözleşmeleri gerçek agent modellerine eşlenebilir | **Karşılandı** | Envelope alanları B1 plan tablosundan birebir alındı; execution isteği alanları (soru, dil, mod, revizyon/hash, geçmiş, bütçe referansı — plan satır 235) A1 iş modelleriyle eşlenecek şekilde K6/K7'de sahiplikle bağlandı; W1 sırası (önce A1 modelleri, sonra B1 sözleşmeleri) korundu |

## 6. Sınırlamalar ve çalıştırılmayan kontroller

- `dotnet build` / test paketi çalıştırılmadı — B0 salt okunur denetimdir; kod değişikliği olmadığından derleme kanıtı gerekmez. Bu bir başarı iddiası değildir; yapılmadı olarak raporlanır.
- RabbitMQ broker kurulmadı, topology declare edilmedi (B2+ kapsamı).
- Python tarafı incelenecek kod içermediğinden Python sahiplik kararları plan metni + kaynak arşivi CONTEXT'iyle sınırlıdır; aio-pika/FastAPI sürüm seçimi B2'de kurulu sürüm belgeleriyle doğrulanmalıdır ([AIO-PIKA#C1] sürüm kapsamı notu).
- Source arşivinde Python migration aracı ve broker mesaj boyut limitine dair parça bulunamadı; bu iki kalem "yetersiz bilgi" olarak açık bırakıldı, hafızadan doldurulmadı.

## 7. Sonraki adım

B1: `docs/ai-agent-plan/contracts/` altında JSON Schema sözleşme kaynağı; A1 iş modelleriyle
eşleme; bu rapordaki K6 (event_sequence/deadline) ve K7 (boyut sınırları) alanlarının sözleşmeye
yerleştirilmesi.
