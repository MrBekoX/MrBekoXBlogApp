# Agent mimarisi belgesi ve A0–A10 aşama takibi

Bu belge, `docs/ai-agent-plan/01-agent-gelistirme-plani.md` A0 fazının çıktısıdır: agent çekirdeğinin ekleneceği yeri, dış portları, iş modeli sınırlarını ve aşama bağımlılıklarını bugünkü kod kanıtlarıyla sabitler. Haberleşme (RabbitMQ, envelope, kuyruk) tasarımı `02-rabbitmq-haberlesme-plani.md`'ne aittir ve burada önerilmez.

Karar temeli: decisions.md D001 (Python + LangGraph), D002 (backend–agent haberleşmesi RabbitMQ, ayrı plan), D003 (iki plan ayrı, diyagramlar korunur).

## 1. Mevcut kod tabanı envanteri (A0 denetim sonucu)

| Konu | Bugünkü durum | Kanıt |
| --- | --- | --- |
| Makale entity | `BlogPost`: Title, Slug (string), Content (ham markdown), Excerpt?, Status, PublishedAt?, ViewCount, LikeCount, IsFeatured, Version (uint), Meta*, ReadingTimeMinutes, AuthorId, CategoryId?, Tags, Comments | `src/backend/Core/Domain/Entities/BlogPost.cs:9-95` |
| Durum | `PostStatus { Draft=0, Published=1, Archived=2 }` | `Core/Domain/Enums/PostStatus.cs:6-11` |
| Slug | `Slug` ValueObject (Türkçe katlama + regex doğrulama); entity alanı düz `string`, VO handler'da üretimde | `Core/Domain/ValueObjects/Slug.cs:9-99`, `UpdatePostCommandHandler.cs:63-70` |
| İçerik biçimi | Ham markdown; HTML sanitization content'e uygulanmaz (react-markdown güvenli render), title/meta'ya uygulanır | `UpdatePostCommandHandler.cs:131-143` |
| Revizyon | İş revizyonu **yok**. `Version` PostgreSQL `xmin` rowversion concurrency token'ı; DTO'lara çıkmaz, geçmiş tutmaz, view-count artışında bile değişir. İçerik hash alanı yok; güncelleme yerinde | `BlogPostConfiguration.cs:32-34`, `PostDetailQueryDto.cs:5-28`, `UpdatePostCommandHandler.cs:131-156` |
| Yayımlı okuma yolu | `Status == Published && !IsDeleted` filtresiyle slug sorgusu; `PostDetailQueryDto` tam Content + Author + Category + Tags; 10 dk cache + grup versiyon invalidasyonu | `GetPostBySlugQueryHandler.cs:22-64`, `PostsEndpoints.cs:200` |
| Profil verisi | Backend'de feature/entity yok; statik `SeoDocuments.cs:18-21` (SiteName, AuthorName, SiteDescription) ve frontend `site-config.ts:19-32` (author, unvan, açıklama, sosyal linkler) | ilgili dosyalar |
| Proje verisi | **Hiçbir yerde yok** (home bileşenleri yalnız post/tag; `geo-entities.ts` teknoloji sözlüğü) | `components/home/`, `lib/geo-entities.ts` |
| Model/embedding ayarı | **Yok.** appsettings bölümlerinde LLM/embedding girdisi yok; backend'de ilgili paket/option sınıfı yok | appsettings anahtar taraması (değerler okunmadı), `grep OpenAI\|Anthropic\|Ollama\|Embedding` boş |
| Yeniden kullanılabilir altyapı | Generic `IReadRepository`/`IWriteRepository` + `IUnitOfWork`; `Result`/`Error` düzeni; Redis `ICacheService` (HybridCacheServiceBase); SignalR `PublicCacheHub` (public cache invalidation; agent progress'i değil) | `Interfaces/Persistence/`, `Infrastructure/Services/CacheService.cs:26`, `Hubs/PublicCacheHub.cs` |
| Eski agent kodu | Çalışma ağacında **yok**; `src/services/ai-agent-service` (FastAPI+LangChain+Ollama+Chroma) `9a452d8`'de eklenip `3dbdef8`'de silindi. `codebase_docs/ai_agent_codebase.md` o kodun dokümanıdır | git log/show; `.claude/rules/building-blocks.md:11` (Messaging kaldırıldı, yeniden ekleme mimari karar ister) |
| Frontend agent durumu | Agent özelliği yok; eşleşenler yalnız SEO/keşif (llms.txt, robots crawler kuralları, dekoratif metin) | `layout.tsx:141`, `robots.ts:20-61`, `discovery-rewrites.ts:1` |

## 2. Agent çekirdeğinin konumu ve paket sınırları

- **Konum:** `src/services/ai-agent-service/app/agent_core` (ortak prompt kural 3; `src/services` bugün yok, A1'de oluşturulur).
- **Paket düzeni (öneri, A1'de somutlaşır):**
  - `agent_core/` — iş modelleri (Pydantic), port arayüzleri, giriş noktaları (`prepare_and_route`, `execute_plan`, `resume`), LangGraph executor. Dış transport'a bağımlısız.
  - `agent_core/adapters/` — test double'lar ve somut sağlayıcı adaptörleri (`ModelProvider`, `EmbeddingProvider`, `WebSearchProvider`, `SourceReader`, `CheckpointStore`, `BudgetStore`).
  - Backend .NET koduna, AMQP kütüphanesine, HTTP response tiplerine ve frontend tiplerine **bağımlılık yok** (plan: "Agent katmanlarının broker kütüphanesine, backend controller'ına veya frontend tiplerine bağımlılığı olmayacak").
- **Çağrılma sözleşmesi:** Dış adaptör girdiyi `ExecutionContext` iş modeline çevirir, agent'ı çağırır; agent `AgentOutcome` + `DomainProgress` üretir. Taşıma yönteminden bağımsızdır.
- **Çalışma deseni gerekçesi:** Planın akışı, modelin kendi araç kullanımını yönlendirdiği agent davranışı ile önceden tanımlı kod yollarını birleştirir; basit ve birleştirilebilir desenlerden başlanıp ihtiyaçla karmaşıklık eklenir [ENG-AGENTS#C1], yönlendirme/orchestrator-worker desenleri farklı görev yapılarına hizmet eder [ENG-AGENTS#C2].
- **Bağlam ilkesi:** `ExecutionContext` yalnız doğrulanmış ve gerekli alanları taşır; agent çalışırken ilgili bilgiyi gerektiğinde getirir, gereksiz araç çıktısı bağlamı şişirmez [ENG-CONTEXT#C1].

## 3. İş modelleri (A1'de tanımlanacak; sınırlar A0'da sabit)

`ExecutionContext`, `AgentOutcome`, `RouteDecision`, `ArticleSnapshot`, `ArticleChunk`, `SourceReference`, `EvidenceItem`, `ResearchPlan`, `ResearchFinding`, `DomainProgress`, `UsageRecord`, `ActionProposal`, `ValidatedActionResult`.

- Durumlar: `completed`, `partial`, `needs_input`, `cancelled`, `failed`. Kuyruğa alınma/teslim iş modeli durumu **değildir**.
- Bu modellerde AMQP header'ı, queue adı, HTTP response nesnesi **yok**.
- Anlam ayrımı (B1'in envelope'a eşleyeceği tanımlar):
  - **`article_revision`:** backend'in atadığı, makale başına monoton, bir yayımlanmış içerik anını (içerik + Published durumu) tanımlayan kimlik. ⚠️ Mevcut `BlogPost.Version` (xmin) bu anlamda kullanılamaz; kaynağına A1 öncesi karar gerekir (A0-rapor §8-10).
  - **`article_content_hash`:** sunulan makale snapshot'ı `Content`'inin UTF-8 SHA-256 özeti; agent gelen snapshot'tan yeniden hesaplar, uyuşmazsa çalışmayı bayat-bağlam hatasıyla reddeder. Komut idempotency hash'i ile ilgisizdir.
  - **`source_id`:** `(article_id, article_revision, chunk_index)` üçlüsü (makale kanıtı) veya `url + erişim zamanı` (web kanıtı); `citations` içinde döner. `chunk_index` A3 ile anlam kazanır.
  - **`run_id`:** backend'in ürettiği ve sahipliğini doğruladığı tek yürütma kimliği; `conversation_id` oturumu temsil eder, yeniden deneme yeni `run_id` alır. Cancel/resume ve terminal sonucun tekrar bulunması `run_id`'ye bağlıdır.

## 4. Mevcut kodun agent tarafında kullanımı

| Mevcut | Agent kullanımı |
| --- | --- |
| `BlogPost` okuma yolu (`GetPostBySlugQueryHandler`, `PostDetailQueryDto`) | Backend, yayımlı makaleden `ArticleSnapshot` (id, revision, hash, title, markdown Content, meta, tags, published/updated zamanları) hazırlayıp EC'ye verir; agent DB'ye erişmez |
| `Slug` VO davranışı | Snapshot doğrulamasında slug normalize/karşılaştırma kuralı olarak yansıtılır (Türkçe katlama dahil) |
| `PostStatus` | Yalnız `Published` makaleler agent'a sunulur; draft/archived bağlam verilemez |
| Markdown format kararı (sanitize'siz content) | A3 bölümlemesi kod-fence korumasıyla yapılır; citation ofsetleri markdown kaynağına göre verilir |
| `Result`/`Error` düzeni | .NET tarafı desenidir; Python tarafı ayrı yazılı hata tipleri tanımlar (aşağıdaki port tablosu); ikisi B1'de eşlenir |
| Redis cache altyapısı | Agent çekirdeği doğrudan kullanmaz; transport tarafının (B planı) ihtiyacına ev sahipliği yapabilir |
| `PublicCacheHub` | Agent progress kanalı değildir; progress, port soyutlaması (`ProgressSink`) üzerinden B planında taşınır |

## 5. Dış portlar (A1 listesi) — veri, hata türleri ve mevcut karşılık

Hata türü sözleşmesi (tüm portlar ortak): `config_error` (eksik/hatalı sağlayıcı yapılandırması, insan-okur mesaj), `validation_error` (girdi iş modeli reddi), `not_found`, `stale_snapshot` (hash/revizyon uyuşmazlığı), `budget_exhausted`, `cancelled`, `provider_error` (dış sağlayıcı arızası, tekrarlanabilirlik bilgisiyle), `timeout`.

| Port (A1) | Sağladığı veri | Mevcut kod karşılığı | Durum |
| --- | --- | --- | --- |
| `ContentRepository` | `ArticleSnapshot` (id, revision, content_hash, title, markdown content, meta, tags, zamanlar), makale listesi/erişimi | Backend okuma yolu mevcut (`GetPostBySlugQueryHandler`); revision/hash alanı yok | Kısmi — snapshot hazırlama backend işi, port Python tarafında tanımlanır |
| `ProfileRepository` | Sahibin tanıtım verisi (ad, unvan, açıklama, sosyal linkler, yetkinlikler) | Yalnız statik: `SeoDocuments.cs:18-21`, `site-config.ts:19-32` | Eksik — veri kaynağı kararı gerekli |
| `ProjectRepository` | Proje kayıtları (ad, açıklama, teknolojiler, linkler) | Yok | Eksik — veri kaynağı kararı gerekli |
| `ModelProvider` | Cevap/özet/plan üretimi (stream + usage) | Yok (hiçbir model paketi/ayarı yok) | Eksik — sağlayıcı kararı gerekli |
| `EmbeddingProvider` | Chunk embedding vektörleri | Yok | Eksik — A3 öncesi karar |
| `WebSearchProvider` | Kontrollü web arama sonuçları | Yok | Eksik — A4 öncesi karar |
| `SourceReader` | URL içerik okuma (temizlenmiş metin) | Yok | Eksik — A4 öncesi karar |
| `CheckpointStore` | LangGraph state checkpoint kayıt/okuma | Yok; Redis altyapısı transport tarafında mevcut | Eksik — A2'de tanımlanır |
| `BudgetStore` | Token/araç/süre bütçesi sorgu ve düşümü | Yok | Eksik — A2'de tanımlanır |
| `CancellationToken` | Süreç içi iptal sinyali | Yok (plan düzeyi; in-process) | A1'de tip olarak gelir |
| `ProgressSink` | `DomainProgress` olaylarını yayma (transport-dönüşümlü) | Yok; transport B planında | Eksik — B0/B1 sözleşmesiyle eşlenir |

Portlar agent paketi içindeki **arayüzlerdir**; backend'in mevcut repository sınıfları (`IBlogPostReadRepository` vb.) Python portlarının karşılığı değildir — backend kendi tarafında veriyi hazırlar, taşima B planının işidir.

## 6. A0–A10 aşama takip tablosu

| Aşama | Durum | Çıktı / doğrulama | Sonraki aşamaya bağımlılıklar |
| --- | --- | --- | --- |
| A0 | Tamamlandı (salt okunur denetim, 2026-10-11) | `docs/ai-agent-plan/phase-reports/A0-rapor.md` + bu belge; `search.cjs verify` valid (30 kaynak, 60 parça); çekirdek konumu, 11 portun veri/hata sözleşmesi ve iş modeli anlamları sabitlendi | A1'e: revizyon kaynağı, profil/proje veri kaynağı ve model sağlayıcı kararları; A2-A10 satırları aşağıda sıraya bağlı |
| A1 | Başlanmadı | — | A0 kararları (§5 port tablosu, §3 iş modeli anlamları) |
| A2 | Başlanmadı | — | A1 iş modelleri; paralel sonuçların ortak state'e birleşimi açık tanımlanmalı [LG-WORKFLOWS#C2] |
| A3 | Başlanmadı | — | A1 `ArticleChunk`/`EmbeddingProvider`; markdown kod-fence korumalı bölümleme |
| A4 | Başlanmadı | — | A2 bütçe/iptal; alt araştırma görevleri için yapılandırılmış eşzamanlılık (hata-iptal birlikte) [PY-ASYNCIO#C1], orchestrator-worker deseni [ENG-AGENTS#C2] |
| A5 | Başlanmadı | — | A4 kanıt kayıtları; kaynak kontrolü |
| A6 | Başlanmadı | — | A2 state; olay üretimi |
| A7 | Başlanmadı | — | A6 olayları |
| A8 | Başlanmadı | — | A2 CheckpointStore/BudgetStore |
| A9 | Başlanmadı | — | A1 `ActionProposal`; backend onay akışı |
| A10 | Başlanmadı | — | Tüm davranışların tamamlanması |

Durum değerleri: Başlanmadı / Devam ediyor / Review / Doğrulandı / Engelli.

## 7. Kapsam sınırları

- Bu belge haberleşme bileşeni (kuyruk, exchange, envelope şeması, consumer/publisher, outbox/inbox) **önermez**; bunlar B0+ kapsamıdır. Yeniden eklenmesi gereken `BuildingBlocks.Messaging` için `.claude/rules/building-blocks.md:11` uyarınca önceden mimari karar alınması şarttır.
- A0 salt okunurdur; buradaki "öneri" niteliğindeki paket düzeni ve tanımlar, A1'in iş modeli çalışmalarına girdi olur, kod değişikliği değildir.
