# W0 Ortak Mimari Kararları — A0 ve B0 sonuçlarının birleşimi

- **Tarih:** 2026-10-11
- **Rol:** W0 birleştirici (A0 + B0 denetim sonuçlarını tek karar setinde birleştirme)
- **Temel:** `feature/ai-agent-integration`, HEAD `8f148ab` (= `origin/main`)
- **Kaynak raporlar:** `docs/ai-agent-plan/phase-reports/A0-rapor.md` + `docs/ai-agent-plan/agent-architecture.md`; `docs/ai-agent-plan/phase-reports/B0-rapor.md` + `docs/ai-agent-plan/integration-architecture.md`
- **Yazılan dosya:** yalnız bu dosya. `progress.md`, `decisions.md` ve hiçbir kod dosyası değiştirilmedi.
- **Amaç:** A1 ve B1 uzmanı bu dosyayı okuyup doğrudan işe başlayabilmeli (main prompt W1 kuralı: "Önce agent iş modelleri; ardından sürümlenmiş mesaj sözleşmeleri").

## 0. Yöntem ve doğrulama

A0 ve B0 raporlarının tüm kod iddiaları kendi checkout'larında dosya/satır kanıtlıdır; bu birleştirmede yeni teknik API iddiası üretilmedi, iki raporun ortak temeli bu oturumda yeniden doğrulandı:

- `node docs/ai-agent-plan/source/tools/search.cjs verify` → `"valid": true, "sources": 30, "chunks": 60, "stages": 23` (iki raporun §1/§2 tablolarındaki sonuçla aynı).
- Repo yapısı kanıtları (bu oturumda çalıştırıldı): `ls src/` → yalnız `backend`, `frontend`; `src/services` **mevcut değil** (A1'de oluşturulacak, A0-rapor §5-3 ile uyumlu). `git ls-files tests/` → **0 dosya**; `git check-ignore -v tests/BlogApp.Server.Api.Tests/BlogApp.Server.Api.Tests.csproj` → `.gitignore:27:tests/` — yani `tests/` dizini git tarafından **yok sayılıyor**. `grep "Project(" BlogApp.sln` → çözümde kayıtlı tek test projesi `BlogApp.Presentation.Api.Tests` = `src\backend\Presentation\Api.Tests\BlogApp.Presentation.Api.Tests.csproj` (git takipli: `git ls-files src/backend/Presentation/Api.Tests/` dolu döndü). `find src/backend/BuildingBlocks -name "*.cs"` → yalnız Caching dosyaları, Messaging yok. `ls src/backend/Core/Application/Common/Interfaces/` → `Data`, `Persistence`, `Services` (Messaging alt dizini henüz yok, oluşturulacak); `Core/Application/Common/Options/` mevcut.
- K1'in migration kanıtı doğrulandı: `src/backend/CLAUDE.md` "Komutlar" bölümünde `dotnet ef migrations add` / `database update` komutları `--project src/backend/Infrastructure/Infrastructure --startup-project src/backend/Presentation/API` ile listeleniyor.
- `.claude/rules/building-blocks.md` "Mevcut moduller" bölümü: "Messaging modulu kaldirildi (2026-04-07 …). Yeniden eklenmesi gerekirse onceden dur ve mimari karar al." (B0 F1 ve A0 §5'in atıf yaptığı kural.)

Dalga tablosu ve "İki planın uygulanma sırası" (main prompt "Aşama bağımlılıkları ve yürütme dalgaları" tablosu; `01-agent-gelistirme-plani.md:477-485`) korundu: W1'de önce A1, ardından A1'in iş modellerine eşlenen B1 sözleşmeleri.

## 1. Ortak sözleşme sınırları

İki planın tek uyum noktası dört iş modelidir: "Dosyalar arasında uyum noktası ExecutionContext, AgentOutcome, DomainProgress ve ActionProposal sözleşmeleridir. Ortak iş modelleri tek bir kaynakta tanımlanır; RabbitMQ envelope'u bu modellerin dışına eklenir" (`01-agent-gelistirme-plani.md:21`). A0 bu modellerin **anlamını ve sınırlarını**, B0 bunların **taşıma karşılıklarını ve sahiplerini** sabitledi; W0 ikisini tek tabloda birleştirir.

| Sözleşme | Yön ve rol | Alan kapsamı (kaynak) | Taşıma karşılığı (B1) |
| --- | --- | --- | --- |
| `ExecutionContext` | Girdi — agent'ın gördüğü tek giriş; transport-dönüşümsüz | `run_id, conversation_id, question, language, mode_preference, article_id, article_revision, article_content_hash, doğrulanmış makale snapshot'ı veya içerik referansı, seçilen metin, tamamlanmış konuşma geçmişi, bütçe profili` (plan A1, `01-…plani.md:170`) | `AgentExecutionRequestedV1.payload` (B0 K7: içerik gömülmez, revizyon/hash **referansı** taşınır) |
| `AgentOutcome` | Terminal çıktı — tekil, nihai sonuç | `selected_mode, status, answer veya report, citations, source_scope, unresolved_questions, usage, varsa ActionProposal` (`01-…plani.md:172`); `status ∈ {completed, partial, needs_input, cancelled, failed}` (`:182`) | Beş terminal olayı: `AgentRunCompletedV1` / `PartiallyCompleted` / `NeedsInput` / `Failed` / `Cancelled` (B1 mesaj türleri, `02-…plani.md:205-212`) |
| `DomainProgress` | Ara çıktı — terminal olmayan sıralı ilerleme olayları | İş modeli listesi (`01-…plani.md:179`); `ProgressSink` portundan dışarı akar (agent-architecture §5 port tablosu) | `AgentRunProgressedV1.payload` + Python'un ürettiği monoton `event_sequence` (K6); `event_sequence` **envelope/payload tarafındadır, iş modelinde değildir** |
| `ActionProposal` | `AgentOutcome` içinde opsiyonel alan + A9'un öznesi | "Düzenlenebilir özet ve içerik hash'i olan ActionProposal" (`01-…plani.md:437`); `ValidatedActionResult` (`:180`) | Gidiş: `AgentActionProposedV1` (Python→Backend), dönüş: `AgentActionResultV1` (Backend→Python kontrol kuyruğu) (`02-…plani.md:213-214, 226, 228`) |

**Paylaşım ve ayrım kuralları (her iki taraf için bağlayıcı):**

1. **Tek tanım kaynağı:** Bu dört model A1'de bir kez, Pydantic olarak tanımlanır (`agent_core/models`); JSON temsilleri `docs/ai-agent-plan/contracts/` altındaki payload şemalarında ifade edilir (bkz. §3). B1 yeni iş modeli alanı **icat etmez**; yalnız eşler (B0-rapor kabul ölçütü 3: "B1 sözleşmeleri gerçek agent modellerine eşlenebilir").
2. **Transport kirlenmez:** "Bu modellerde AMQP header'ı, queue adı, HTTP response nesnesi yok" (agent-architecture §3). `message_id`, `correlation_id`, `causation_id`, `deadline_at`, `producer`, `trace_context`, `schema_version` envelope'a aittir (B1 tablo, `02-…plani.md:183-196`); iş modellerinde görünmez. Queue/exchange/dead-letter kavramları iş modeli durumu değildir; "Mesajın kuyruğa alınması veya teslim edilmesi iş modeli durumu değildir" (`01-…plani.md:182`).
3. **Durum ayrımı:** `AgentOutcome.status` yalnız beş terminal/ework değeri taşır; "kuyruğa alındı", "ACK'lendi", "publish edildi" gibi teslim durumları backend run kaydının/projection'ın durumudur (B0 K4: kabul = .NET, yürütme = Python, gösterim = .NET projection).
4. **Anlam sözlüğü (A0 §7, B1'in envelope'a eşleyeceği tanımlar — değiştirilmez):**
   - `article_revision`: backend'in atadığı, makale başına monoton, yayımlanmış içerik anını tanımlayan kimlik. ⚠️ Mevcut `BlogPost.Version` (xmin rowversion) **bu anlamda kullanılamaz** (`BlogPostConfiguration.cs:32-34`).
   - `article_content_hash`: sunulan snapshot `Content`'inin UTF-8 SHA-256 özeti; agent yeniden hesaplar, uyuşmazsa `stale_snapshot` hatası. İdempotency komut hash'iyle (`IdempotencyRequestHasher.cs`) ilgisizdir.
   - `source_id`: `(article_id, article_revision, chunk_index)` (makale kanıtı) veya `url + erişim zamanı` (web kanıtı); `chunk_index` A3 ile anlam kazanır.
   - `run_id`: backend'in ürettiği ve sahipliğini doğruladığı tek yürütma kimliği; `conversation_id` oturumu temsil eder, yeniden deneme yeni `run_id` alır (B0 K5 ile birleşik: sahip kimliği backend'de JWT/misafir oturumundan yazılır).
5. **Hata türleri ortaktır** (agent-architecture §5): `config_error, validation_error, not_found, stale_snapshot, budget_exhausted, cancelled, provider_error, timeout`. B1, `AgentRunFailedV1`/`NeedsInput` payload'larında bu türleri kod olarak taşır; iki taraf aynı enum'u kullanır.

## 2. Dosya/modül sahiplik haritası

Her satırın sahibi tek yazardır; aynı dosyada iki yazar olmaz (main prompt "Paralel çalışma ve dosya sahipliği kuralları").

### 2.1 A1 — Python agent paketi (sahip: A1 uzmanı)

| Konum | İçerik | Kanıt/kaynak |
| --- | --- | --- |
| `src/services/ai-agent-service/` | Yeni servis kökü (`src/services` bugün yok — `ls` kanıtı §0) | Ortak prompt kural 3; A0-rapor §5 |
| `…/app/agent_core/` | İş modelleri (Pydantic), port arayüzleri, giriş noktaları (`prepare_and_route`, `execute_plan`, `resume`), LangGraph executor. **Transport bağımsız:** .NET/AMQP/HTTP/frontend tipine bağımlılık yok | agent-architecture §2 |
| `…/app/agent_core/models/` | `ExecutionContext, AgentOutcome, RouteDecision, ArticleSnapshot, ArticleChunk, SourceReference, EvidenceItem, ResearchPlan, ResearchFinding, DomainProgress, UsageRecord, ActionProposal, ValidatedActionResult` + `RunStatus` enum | plan A1 listesi (`01-…plani.md:170-182`) |
| `…/app/agent_core/ports/` | 11 port: `ContentRepository, ProfileRepository, ProjectRepository, ModelProvider, EmbeddingProvider, WebSearchProvider, SourceReader, CheckpointStore, BudgetStore, CancellationToken, ProgressSink` (`01-…plani.md:184`) + §1.5'teki ortak hata türleri | agent-architecture §5 tablo |
| `…/app/agent_core/adapters/` | `test_doubles/` (sözleşme testleri için) ile somut sağlayıcı adaptörleri ayrı alt dizinlerde; "Test double ile gerçek sağlayıcı arasındaki ayrım açıktır" kabul ölçütü | agent-architecture §2; `01-…plani.md:193` |
| `…/app/messaging/` | intake/control/content consumer'lar, agent outbox relay (B2/B4/B5'te dolar; **B1'de sadece `contracts/` alt dizini oluşur**) | B0 K2 consumer konumları |
| `…/app/messaging/contracts/` | Envelope + mesaj Pydantic modelleri (B1 eşlemesinin Python tarafı). **Kural:** `agent_core` hiçbir koşulda `app/messaging`'i import etmez; yön tek yönlüdür (messaging → agent_core) | integration-architecture §4 "Python tarafı" (açık kalem W0'da sabitlendi, §5 Ç2) |
| `…/tests/` | pytest; `docs/ai-agent-plan/contracts/` şemalarını repo-kökü göreli yoldan okuyan sözleşme testleri dahil | §5 Ç2 çözümü |

### 2.2 B1 — .NET sözleşme/DTO tarafı (sahip: B1 uzmanı)

| Konum | İçerik | Aşama | Kanıt/kaynak |
| --- | --- | --- | --- |
| `docs/ai-agent-plan/contracts/` | **Tek JSON Schema kaynağı** (her iki dilin okuduğu). Önerilen düzen: `contracts/v1/` (envelope + mesaj payload şemaları), `contracts/fixtures/` (`valid/` + `invalid/` örnekleri — "iki dil aynı fixture'ları okuyabilir" kabul ölçütü) | B1 | integration-architecture §4 ilk satır; `02-…plani.md:179, 241` |
| `src/backend/Core/Application/Common/Interfaces/Messaging/` | `IOutboxService`, `IAgentCommandPublisher`, `IAgentEventConsumer` soyutlamaları (dizin bugün yok; `Interfaces/` altında `Data/Persistence/Services` var — oluşturulacak) | B1/B3 | integration-architecture §4; `ls` kanıtı §0 |
| `src/backend/Core/Application/Common/Options/AgentMessagingSettings.cs` | Broker bağlantı, `MaxPayloadBytes` (K7), deadline varsayılanları (`ServerLimitsSettings` deseni); dizin mevcut | B1/B2 | integration-architecture §4; `ServerLimitsSettings.cs:11-16` |
| `src/backend/BuildingBlocks/BuildingBlocks/Messaging/` (B2'de) | RabbitMQ bağlantı ömrü, confirm'lu publisher, consumer tabanı, topology initializer; envelope/message .NET DTO'ları `Messaging/Contracts/` altında | B2 | integration-architecture §4; W0 notu: yeniden ekleme öncesi karar kaydı şart (§5 Ç3) |
| `src/backend/Core/Domain/Entities/` | `AgentRun`, `OutboxMessage`, `AgentEventInbox` | B3/B4 | integration-architecture §4 |
| `src/backend/Infrastructure/Infrastructure/Messaging/` | Outbox publisher + backend event consumer hosted service'ler (`AddHostedService` deseni, `DependencyInjection.cs:104-105`) | B3/B4 | B0 K2 |
| `src/backend/Presentation/API/Endpoints/AgentEndpoints.cs`, `Hubs/AgentRunsHub.cs` | Kabul uçları (202 + `IdempotencyHelper` deseni) + `agent-run:{runId}` hub'ı | B4/B9-B10 | integration-architecture §2 adım 1-3, 9; K5 |
| `src/backend/Presentation/Api.Tests/` | Sözleşme ve akış testleri; öneri: `Messaging/` alt klasörü | B1+ | **B0 raporunun önerdiği `tests/BlogApp.Presentation.Api.Tests/` yolu düzeltildi — bkz. §5 Ç1** |

### 2.3 Ortak JSON şema konumu (iki tarafın okuyacağı tek yer)

- **Tek kaynak:** `docs/ai-agent-plan/contracts/` — B0'ın önerdiği konum aynen onaylandı (B0-rapor §7: "B1: `docs/ai-agent-plan/contracts/` altında JSON Schema sözleşme kaynağı"). .NET DTO'lar ve Python Pydantic modelleri aynı fixture'larla doğrulanır (`02-…plani.md:179`).
- **Kopya alınmaz:** servis aynı repoda yaşadığı sürece her iki tarafın testleri şemaları repo köküne göreli yoldan okur (`src/services/ai-agent-service/tests/` → repo kökü → `docs/ai-agent-plan/contracts/`). B0'ın "JSON Schema kopyaları/konfeti" notu bu yüzden gerekmesizleşti; servis ileride ayrı repoya çıkarsa kopya + eşitlik testi desenine geçilir (§6 açık soru 9).
- **Sürümleme:** dizin başına major sürüm (`contracts/v1/…`), envelope `schema_version` alanı bu major sürümü taşır (`02-…plani.md:188`). Bilinmeyen sürüm, eksik alan, aşırı boyut, hatalı tür kontrollü reddedilir (`:241`).

### 2.4 Test konumları

| Taraf | Konum | Not |
| --- | --- | --- |
| .NET sözleşme/akış testleri | `src/backend/Presentation/Api.Tests/` (mevcut, git takipli, `BlogApp.sln` kayıtlı, net10.0) | `tests/` dizini `.gitignore:27` ile yok sayıldığından oraya test YAZILMAZ (§5 Ç1) |
| Python sözleşme/birim testleri | `src/services/ai-agent-service/tests/` (A1 oluşturur) | Pydantic model + port test double testleri; `adapters/test_doubles` ile gerçek sağlayıcı ayrımı |
| Ortak sözleşme fixture'ları | `docs/ai-agent-plan/contracts/fixtures/` | Her iki dilin testleri aynı dosyaları okur; `valid/` ve `invalid/` alt kümesi, B1 kabul ölçütünün kanıt dosyalarıdır |
| Test executor (agent hazır olana dek) | .NET akış testleri: `src/backend/Presentation/Api.Tests/` altında test double publisher/consumer; broker'a bağlanan uçtan uca executor: Python `tests/` altında (A1 ile sabit) | B0 §4 üç katmanlı işaretleme: `producer: "test-executor"`, `execution_origin: "test_executor"` + Production fail-fast |

## 3. Migration sahipliği ve sırası

**Sahiplik (B0 K1, aynen onaylandı):**

- Backend şeması EF Core ile **Infrastructure assembly**'den yönetilir; tek konsolide migration politikası korunur (`src/backend/CLAUDE.md` Komutlar bölümü; `20260407130831_InitialCreate`). Dev'de manuel, prod'da `RunMigrationsOnStartup=true` ile açılışta (K8).
- **Backend EF migration'ları agent tablolarına asla dokunmaz.** Python kendi tablolarının tek sahibidir; kendi migration aracıyla (Alembic adayı; araç seçimi arşivde karşılıksız olduğundan B4 öncesi kurulmuş sürüm belgesiyle doğrulanacak) yönetir.
- İki taraf aynı PostgreSQL sunucusunu paylaşabilir; agent kendi schema'sında (`agent`) ayrı DB rolüyle çalışır; **schema'lar arası FK kurulmaz** — servis sınırı broker sözleşmesidir (`02-…plani.md:38`).

**Sıra (dalga tablosuna göre; hiçbir dalga iki tarafın migration'ını aynı elden yazmaz):**

| Aşama | Migration işi | Sahip | Not |
| --- | --- | --- | --- |
| A1, B1 (W1) | Yok — yalnız kod + şema | — | Şema dosyası migration değildir |
| B3 | Backend: `AgentRun` + `OutboxMessage` tabloları (EF migration, Infrastructure) | B3 uzmanı | `UnitOfWork.BeginTransactionAsync` + `ExecuteResilientAsync` ile "iş kabulü + outbox tek transaction" (B0 F2; `EnableRetryOnFailure` + açık transaction execution-strategy uyumlu sarmalanmalı) |
| B4 | Backend: `AgentEventInbox` (EF); Python: inbox/job tabloları (kendi aracı, `agent` schema'sı) | iki ayrı uzman, ayrı dosyalar | Python migration aracı kararı **B4 öncesi** kapanmış olmalı (§6 açık soru 5) |
| A8 | Python: checkpoint store kalıcılığı (DB-backed ise `agent` schema'sında) | A8 uzmanı | Backend'e dokunmaz |
| B8 | Python: içerik indeks tabloları (`agent` schema'sı); backend tarafı yeni tablo gerektirmez | B8 uzmanı | `ArticleContentChangedV1` sync hattı |

**Kural:** her migration sahibinin aracı ve kendi şeması ile yazılır; bir fazın backend ve Python migration'ları farklı uzmanların dosya sahipliğindedir ve tek PR'da birleştirilse bile araç/süreç ayrı kalır.

## 4. A0 ve B0'ın örtüşen bulgularının birleşimi (çelişme yok, tek çizgi)

İki raporun birleştiği ve **karşılıklı olarak doğruladığı** ortak zemin (W0 bunları teyit etti, tekrar argüman etmiyor):

- Çalışma ağacında ne Python ne messaging altyapısı var (A0 §5; B0 §1 grep/find kanıtları; bu oturum `ls src/` teyidi) → A1 ve B2 yeşil alan, ama şekilsiz değil: kaldırılan `BlogApp.Messaging` + `ai-agent-service` (`3dbdef8`) ders ve şekil referansıdır; eski dosyalar **birebir geri getirilmez**, RMQ client 7.x API'leriyle yeniden yazılır (B0 F1 + [RMQ-DOTNET#C1/#C2]).
- Agent çekirdeği envelope görmez; .NET tarafı agent davranışı içermez (A0 kabul 3; B0 §2 ayırma kuralı).
- `BuildingBlocks.Messaging` yeniden ekleme `.claude/rules/building-blocks.md` uyarınca önceden mimari karar ister → B0'ın B2 planı bu kararı taşır; kararın `decisions.md`'ye işlenmesi ana orkestratördedir (§5 Ç3, §6 açık soru 7).
- Uçtan uca sahiplik zinciri B0 §2 tablosundaki 10 adımla sabittir; A0'ın port tablosu (§5) Python tarafındaki adımların (5-7) içerik sözleşmesini verir. İki tablo çakışmaz: A0 taşıma önermez, B0 agent algoritması yazmaz.

## 5. Çelişen/uyumsuz kararlar ve W0 çözümleri

| # | Konu | Çelişki/uyumsuzluk (kanıtla) | W0 çözümü |
| --- | --- | --- | --- |
| Ç1 | .NET test klasörü | B0 integration-architecture §4 test konumunu `tests/BlogApp.Presentation.Api.Tests/` diye önerir ve "mevcut test projesi" der. Gerçek: `tests/` `.gitignore:27` ile yok sayılıyor (`git check-ignore` kanıtı §0); git takipli ve çözümde kayıtlı mevcut proje `src/backend/Presentation/Api.Tests/` (`BlogApp.sln` Proje kaydı; `git ls-files` dolu). B0'ın önerdiği yola yazılan test **commit edilemezdi** | B1 sözleşme/akış testleri **`src/backend/Presentation/Api.Tests/`** altına (öneri: `Messaging/` alt klasörü) yazılır. `tests/BlogApp.Server.Api.Tests/` gitignored yerel bir dizindir; temel olarak kullanılmaz. B0 raporundaki yol, bu dosya ile düzeltilmiş sayılır; B1 uzmanı bu tabloyu esas alır |
| Ç2 | Python sözleşme dizini + şema kopyası | B0 §5 açık kaleme devretti: "Python sözleşme modülünün kesin dizin yolu — A1 repo iskeleti bekliyor"; §4'te ise `schemas/` altına "JSON Schema kopyaları" önermişti (kopya = sürülme riski) | Sabitlendi: `src/services/ai-agent-service/app/messaging/contracts/` (envelope + mesaj Pydantic). **Kopya yok:** her iki dil şemaları `docs/ai-agent-plan/contracts/`'tan repo-kökü göreli okur (tek kaynak). İthalat yönü kuralı: `agent_core` → `messaging` import'u yasak |
| Ç3 | Messaging modülünün yeniden eklenmesi | `.claude/rules/building-blocks.md`: "Yeniden eklenmesi gerekirse onceden dur ve mimari karar al." ↔ B0 integration-architecture §4 modülü B2 için doğrudan planlamış | B2'den **önce** bu kararın `decisions.md`'ye D00X olarak işlenmesi gerekir — dosya ana orkestratörün olduğundan W0 işlemeyi burada kaydeder (§6 açık soru 7). B1 bu kararı beklemez (module kurmaz, yalnız şema + Application soyutlaması üretir) |
| Ç4 | Eski AI agent kodunun rolü | A0 §10.4 "ders olarak okunsun, kod tabanı olarak yeniden kurulmasın" önerisi ↔ B0 F1 "şekiller B2+ için geri kazanılabilir referans" | Çelişki değil, kademe: **ders + mimari şekil referansı** (bağlantı ömrü, outbox claim/backoff, inbox durum makinesi, session-claim hub deseni) evet; **dosya/RESTORE hayır** (eski client major API'si). A1 eski Python paketini scaffold olarak kullanmaz; B2 eski .NET dosyalarını kopyalamaz |
| Ç5 | `article_revision` kaynağı | A0 §10.1 mekanizmayı açık karar olarak ana orkestratöre bıraktı; B0 K7 execution isteğinin revizyon/hash referansı taşımasını şart koşuyor; A1 EC şeması alanı zorunlu istiyor | Semantik sabittir (§1.4: backend atamalı, monoton); A1 alanı **tip olarak** tanımlar, B1 envelope'da opak taşır — W1 kodu bu karara **engellenmez**. Mekanizma kararı (DTO alanı mı, snapshot tablosu mu) B3 backend şemasından önce kapanmalıdır (§6 açık soru 1). W0 varsayılan öneri: backend okuma yoluna gerçek revizyon alanı + snapshot tablosu değerlendirmesi, karar ana orkestratörde |
| Ç6 | DomainProgress → transport eşlemesi | A0 `ProgressSink` portunu "B0/B1 sözleşmesiyle eşlenir" diye bıraktı; B1 mesaj listesinde karşılık `AgentRunProgressedV1` | Eşleme sabitlendi (§1 tablo): her `DomainProgress` olayı Python tarafından `AgentRunProgressedV1` payload'ına, run başına monoton `event_sequence` ile yazılır (K6); terminalde `AgentOutcome` tek terminal olayına dönüşür. Backend projection sequence koruması uygular, terminal sonrası düşük sequence uygulamaz (K6) |

## 6. A1 ve B1'e somut giriş kararları

### A1 uzmanı için (hemen başlayabilir)

1. **Paket:** `src/services/ai-agent-service/`; Python import kökü `agent_core` (`app/` paket köküdür). Bağımlılık yönetimi ve yapılandırma A1'in ilk işidir (`01-…plani.md:168`); pydantic v2 (A1 kaynakları: PYDANTIC-MODELS, JSON-SCHEMA).
2. **Modüller:** `agent_core/models/` (13 iş modeli + `RunStatus`), `agent_core/ports/` (11 port), `agent_core/adapters/` (`test_doubles/` ayrık), LangGraph executor ve üç giriş noktası (`prepare_and_route`, `execute_plan`, `resume`) — router kararının yeniden model çağrısıyla hesaplanmasını önle (`01-…plani.md:186`).
3. **Alan biçimi:** alan adları `snake_case`, JSON temsil `docs/ai-agent-plan/contracts/` payload şemalarıyla birebir; zamanlar UTC ISO 8601 (`02-…plani.md:239`). `status` yalnız beş değer; teslim durumları yok (§1.3).
4. **Hata tipleri:** `agent_core` ortak hata enum'u (§1.5); `config_error` mesajları insan-okur (`01-…plani.md:192`).
5. **EC'de şu alanlar backend doldurur, A1 yalnız tip tanımlar:** `run_id, article_revision, article_content_hash, bütçe profili` — mekanizma B3'e kadar kapanacak açık karardır (Ç5), A1'i engellemez.
6. **Test:** `…/tests/` altında; paket "dış adaptör olmadan test girdisiyle çağrılabilir" (`01-…plani.md:190`). Test double sonuçları gerçek sağlayıcı başarısı sayılmaz (main prompt kural 95).

### B1 uzmanı için (A1 modelleri sabitlenince başlar; şema iskeleti A1'i beklemeden hazırlanabilir)

1. **Şema kaynağı:** `docs/ai-agent-plan/contracts/v1/` — `envelope.schema.json` (12 alan, `02-…plani.md:183-196` tablo) + 17 mesaj türü için payload şemaları (`:202-217` listesi); `contracts/fixtures/{valid,invalid}/` ortak örnekler.
2. **Sürümleme:** major sürüm dizin adında (`v1`), envelope `schema_version` tamsayı; bilinmeyen sürüm kontrollü reddedilir. Yeni sürüm = yeni dizin, eski şema dondurulur.
3. **Payload eşleme tablosu (B1'in üreteceği sözleşmenin iskeleti, W0 sınırlarıyla):** EC alanları → `AgentExecutionRequestedV1.payload` (revizyon/hash referans, içerik gömülmez — K7); AO → 5 terminal olayı; DomainProgress → `AgentRunProgressedV1` + `event_sequence`; ActionProposal/ValidatedActionResult → `AgentActionProposedV1`/`AgentActionResultV1`. Run olay payload'larına `execution_attempt`/`fencing_token`; transport retry ile yürütme denemesi ayrı alanlar (`02-…plani.md:237`, K6).
4. **Producer enum:** `"backend-net"`, `"agent-py"`, `"test-executor"` (B0 §4 üç katmanlı işaretleme); producer kimliği broker yetkileriyle bağlanır (`02-…plani.md:198`).
5. **Boyut sınırı:** `AgentMessaging:MaxPayloadBytes` (başlangıç önerisi 256 KiB; B1 sabitler), publisher ve consumer iki tarafta doğrular (K7). Sonuç raporları için ayrı, daha geniş ama sınırlı sonuç üst sınırı.
6. **.NET tarafı çıktısı:** `Common/Options/AgentMessagingSettings.cs` + `Common/Interfaces/Messaging/` soyutlamaları + `Api.Tests/Messaging/` şema doğrulama testleri. **BuildingBlocks.Messaging modülü B1'de kurulmaz** (B2; Ç3 kararı sonrası); envelope DTO'ları B2'de `Messaging/Contracts/` altında gelir.
7. **Kabul:** her iki dil aynı fixture'ları okur; eksik alan/bilinmeyen sürüm/aşırı boyut/hatalı tür kontrollü reddedilir (`02-…plani.md:241`).

## 7. Açık sorular (karar gerektirir, W1 kodunu engellemez)

| # | Soru | Karar sahibi | Kapanması gereken son nokta |
| --- | --- | --- | --- |
| 1 | `article_revision` üretim mekanizması: `PostDetailQueryDto`'ya gerçek revizyon alanı mı, snapshot tablosu mu (A0 §10.1; Ç5) | Ana orkestratör | B3 backend şemasından önce |
| 2 | Profil/proje veri kaynağı: `ProfileRepository`/`ProjectRepository` portlarını besleyecek kaynak (A0 §10.2; bugün yalnız statik `SeoDocuments.cs:18-21`, `site-config.ts:19-32`) | Ana orkestratör | A3 chunking/B8 profil sync öncesi (port imzaları A1'de yine tanımlanır) |
| 3 | Model/embedding sağlayıcı ve konfigürasyon yeri (A0 §10.3; config sıfırdan) | Ana orkestratör (D001/D006 çizgisi) | A2 öncesi |
| 4 | Misafir agent erişimi ve kota oranları — ürün kararı (B0 K5; teknik sınır sabit: sunucu üretimi HttpOnly misafir kimliği, grup katılımı sahip kilitli) | Kullanıcı/ana orkestratör | B9/B10 UI öncesi |
| 5 | Python migration aracı seçimi (Alembic adayı; kaynak arşivinde karşılık yok — B0 §6) | B4 uzmanı + kaynak doğrulaması | B4 öncesi |
| 6 | Broker mesaj boyutu/çerçeve limitlerinin kurulu broker sürümü belgesiyle doğrulanması (B0 K7) | B2 uzmanı | B2 |
| 7 | `BuildingBlocks.Messaging` yeniden ekleme kararının `decisions.md`'ye D-kimliğiyle işlenmesi (Ç3; `.claude/rules/building-blocks.md` uyarısı) | **Ana orkestratör** | B2'den önce |
| 8 | Prod `mem_limit: 300m` kapasite gözden geçirmesi (B0 K8/F5) | B11 | B11 |
| 9 | `docs/ai-agent-plan/contracts/` tek-checkout varsayımı: servis ileride ayrı repoya çıkarsa şema kopyası + eşitlik testi desenine geçiş (§2.3) | Ana orkestratör | Yalnız kayıt; bugün eylem yok |

## 8. W0 kabul kontrolü

- Her karar yukarıda adı geçen kaynak raporun bölümüne veya bu oturumda çalıştırılan komut çıktısına dayanır (§0 kanıt listesi); hiçbir karar hafızadan üretilmedi.
- W0 salt karar dosyası yazdı: `docs/ai-agent-plan/phase-reports/W0-ortak-mimari-kararlari.md`. Başka hiçbir dosya oluşturulmadı/değiştirilmedi; `git status` çalışma ağacındaki diğer girdilere dokunmadı.
- Çalıştırılan kontroller: `node docs/ai-agent-plan/source/tools/search.cjs verify` (valid), `ls src/`, `git ls-files tests/`, `git check-ignore -v`, `grep "Project(" BlogApp.sln`, `git ls-files src/backend/Presentation/Api.Tests/`, `find src/backend/BuildingBlocks -name "*.cs"`, `ls src/backend/Core/Application/Common/Interfaces/`, `src/backend/CLAUDE.md` okuma, `.claude/rules/building-blocks.md` okuma. Build/test koşusu **yapılmadı** — W0 kod değişikliği içermeyen birleştirme fazıdır; bu bir başarı iddiası değil, kapsam bildirimidir.
