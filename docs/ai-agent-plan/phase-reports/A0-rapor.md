# A0 Faz Raporu — Mevcut agent yapısını ve kapsamı doğrula

- **Faz:** A0 (salt okunur mimari denetim)
- **Tarih:** 2026-10-11
- **Branch / temel:** `feature/ai-agent-integration`, HEAD `8f148ab` (= `origin/main`)
- **Rol:** Bağımsız A0 faz uzmanı
- **Yazılan dosyalar:** `docs/ai-agent-plan/phase-reports/A0-rapor.md` (bu dosya), `docs/ai-agent-plan/agent-architecture.md`
- **Dokunulan diğer dosya:** yok. `progress.md` ve `decisions.md` değiştirilmedi. Hiçbir kod dosyası değiştirilmedi.

## 1. Çalıştırılan kontroller ve komutlar

| Kontrol | Komut | Sonuç |
| --- | --- | --- |
| Kaynak arşivi doğrulama (EK maddesi) | `node docs/ai-agent-plan/source/tools/search.cjs verify` | `valid: true, sources: 30, chunks: 60, stages: 23`; kontroller: metadata, source_paths, note_hashes, snapshot_records, stage_links, json_yaml_sync |
| A0 teknik CONTEXT hazırlama (plan A0 bölümü) | `node docs/ai-agent-plan/source/tools/search.cjs search --stage A0 --query "Agent mimarisi workflow ve kaynak sınırları" --format prompt` | CONTEXT döndü: [ENG-AGENTS#C1], [ENG-AGENTS#C2], [ENG-CONTEXT#C1], [ENG-CONTEXT#C2] (ikinci aramada ayrıca [LG-WORKFLOWS#C2], [PY-ASYNCIO#C1]) |
| A0 kaynak eşlemesi | `node docs/ai-agent-plan/source/tools/search.cjs list --stage A0` | LG-WORKFLOWS, PY-ASYNCIO, DOCKER-COMPOSE, ENG-AGENTS, ENG-CONTEXT — plan A0 satırındaki kaynak listesiyle birebir uyumlu |
| Model/embedding ayar taraması | appsettings dosyalarında anahtar adı listeleme (string değerler `<redacted>` olarak maskeylendi, hiçbir değer okunmadı/loglanmadı); backend'de `openai|anthropic|ollama|embedding|langchain` grep'i | Aşağıda §4 |
| Eski agent kodu iz sürme | `git log --all --diff-filter=A -- "*ai-agent-service*"`, `git show 3dbdef8 --stat` | Aşağıda §5 |
| Frontend agent taraması | `src/frontend/blogapp-web/src` altında `agent|chat|assistant|openai|llm|embedding|vector` grep'i (ts/tsx) | Aşağıda §6 |

Çalıştırılmayan kontrol yok; denetim kapsamında istenen her madde yukarıdaki komutlar ve dosya okumalarıyla gerçekleştirildi. Backend derlemesi/test koşusu bu fazın kapsamında değildi (kod değişikliği yapılmayan salt okunur denetim).

## 2. Makale veri modelinin mevcut biçimi (Core/Domain, Core/Application)

### 2.1 Entity ve alanlar

`BlogPost` — `src/backend/Core/Domain/Entities/BlogPost.cs:9-95`:

- `Title`, `Slug` (düz `string`, ValueObject tipi değil), `Content` (düz `string`, **ham markdown**), `Excerpt?`, `FeaturedImageUrl?`, `Status` (`PostStatus`), `PublishedAt?`, `ViewCount`, `LikeCount`, `IsFeatured`, `Version` (`uint`, `private set`), `MetaTitle/MetaDescription/MetaKeywords?`, `ReadingTimeMinutes`, `AuthorId`, `CategoryId?`, `Tags`, `Comments`.
- Domain davranışları: `GetExcerpt`, `CalculateReadingTime`, `Publish()`, `Archive()`, `Unpublish()` (BlogPost.cs:40-94).
- `BaseAuditableEntity` (`Core/Domain/Common/BaseAuditableEntity.cs`): `CreatedAt`, `CreatedBy`, `UpdatedAt?`, `UpdatedBy?`, `IsDeleted`, `DeletedAt?`.
- `PostStatus` — `Core/Domain/Enums/PostStatus.cs:6-11`: `Draft=0, Published=1, Archived=2`. Başka durum yok.
- `Tag` — `Core/Domain/Entities/Tag.cs:8-15`: `Name`, `Slug`; `BlogPost.Tags` çok-çoğa.
- `Slug` ValueObject — `Core/Domain/ValueObjects/Slug.cs:9-99`: Türkçe karakter katlama + `^[a-z0-9]+(?:-[a-z0-9]+)*$` doğrulama. Entity alanı `string` olduğundan VO yalnız handler'da üretim için kullanılıyor (`UpdatePostCommandHandler.cs:63,68`).

### 2.2 Revizyon durumu — A1 için kritik bulgu

- `BlogPost.Version`, EF yapılandırmasında PostgreSQL `xmin` **rowversion concurrency token**'dır: `Infrastructure/Persistence/Configurations/BlogPostConfiguration.cs:32-34` (`.IsRowVersion()`), InitialCreate migration `xmin = table.Column<uint>(type: "xid", rowVersion: true)`. Bu bir iş revizyon numarası değildir: opaktır, satırın her güncellemesinde değişir (`IncrementViewCountAsync` dahil), DTO'ya çıkmaz (`PostDetailQueryDto.cs:5-28` içinde `Version` yok) ve geçmiş tutmaz.
- **İçerik hash alanı yok.** `src/backend/Core` altında "hash" geçen tek yapılar idempotency (`IdempotencyRequestHasher.cs:19-20`, SHA256 komut hash'i) ve şifre hash'idir; makale içeriğiyle ilgisiz.
- **Snapshot/revizyon geçmişi tablosu yok.** `UpdatePostCommandHandler.cs:131-156` içeriği yerinde günceller; eski içerik kaybolur. Yayından kaldırma `Unpublish()` ile `Status=Draft` olur; arşiv `Archive()`.
- Sonuç: A1'in `article_revision` ve `article_content_hash` alanları **bugünkü kodda karşılıksızdır**; anlam tanımı §7'de, açık karar §8'de.

### 2.3 İçerik biçimi ve yayımlı okuma yolu

- İçerik **ham markdown**'tır; `UpdatePostCommandHandler.cs:132-134` yorumu açıkça belirtir: frontend `react-markdown` ile (rehype-raw olmadan) render eder, HTML sanitization atlanır. Title/Excerpt/Meta alanları ise `IHtmlSanitizerService` ile sanitize edilir (UpdatePostCommandHandler.cs:131-143).
- Yayımlı makale okuma: `GetPostBySlugQueryHandler.cs:36-38` — `p.IsDeleted == false && p.Status == PostStatus.Published` filtresi, `IBlogPostReadRepository.GetBySlugAsync` benzeri `PostsRead.Query()` üzerinden; `PostDetailQueryDto` tam `Content` + Author + Category + Tags + CommentCount taşır (PostDetailQueryDto.cs:5-28). 10 dk cache (`PostCacheKeys.BySlug`), cache ısrarı `PostCacheKeys.ListGroup` versiyon rotasyonu ile kırılır (UpdatePostCommandHandler.cs:168-182).
- Endpoint'ler: `Presentation/API/Endpoints/PostsEndpoints.cs` — public `GET /slug/{slug}`, `GET /`, `GET /featured`; role korumalı yazma uçları (satır 32-413).
- Repository portları: genel `IReadRepository<T>`/`IWriteRepository<T>` (`Application/Common/Interfaces/Persistence/`), makaleye özel `IBlogPostReadRepository` (`GetBySlugAsync`, `GetPublishedPostsAsync`, `IncrementViewCountAsync`, …) ve `IUnitOfWork.PostsRead/PostsWrite` (`IUnitOfWork.cs:23-37`).

## 3. Profil ve proje verisi kaynakları

- **Backend'de Profile veya Project feature/entity yok.** `Core/Application/Features` altında yalnız AuthFeature, CategoryFeature, MediaFeature, PostFeature, TagFeature var. `BlogPost.Author` → `User` entity'si (kimlik verisi, tanıtım verisi değil).
- Profil verisi bugün iki statik yerde:
  - Backend: `Presentation/API/Seo/SeoDocuments.cs:18-21` — `SiteName = "MrBekoX"`, `AuthorName = "Berkay Kaplan"`, `SiteDescription` (llms.txt/sitemap/RSS üretiminde kullanılıyor).
  - Frontend: `src/frontend/blogapp-web/src/lib/site-config.ts:19-32` — `AUTHOR_NAME`, `AUTHOR_JOB_TITLE`, `AUTHOR_DESCRIPTION`, `GITHUB_URL`, `TWITTER_URL`, `LINKEDIN_URL` (hepsi `NEXT_PUBLIC_*` ile override edilebilir).
- **Proje (portfolio) verisi hiçbir yerde yok:** `components/home/` altında yalnız `home-posts-section.tsx`, `home-recent-posts.tsx`, `home-tags-section.tsx` var; projeleri listeleyen bir veri kaynağı bulunamadı. `lib/geo-entities.ts` bir teknoloji adı → Wikipedia/doküman URL sözlüğüdür (SEO/GEO), proje verisi değildir.
- Sonuç: A1'in `ProfileRepository` ve `ProjectRepository` portlarının **arkasında bugün doldurulabilir bir veri kaynağı yok**; A1 öncesi veri kaynağı kararı gerekir (§8).

## 4. Model ve embedding ayarları

- `Presentation/API/appsettings.json` bölümleri (anahtar adları; **değerler okunmadı**): Logging, Serilog, ConnectionStrings, JwtSettings, AdminUser, CorsOrigins, IpRateLimiting, ServerLimits, AllowedHosts. `appsettings.Development.Example.json` ve `appsettings.Production.Example.json` aynı bölümler (artı `Database`, `InternalHosts`). **Hiçbir LLM/embedding bölümü yok.**
- Backend `.cs`/`.csproj` taramasında `OpenAI|Anthropic|Ollama|Embedding|LangChain` geçen dosya yok. Frontend `env.client.ts`/`env.server.ts`'de de AI anahtarı yok.
- DI'da bağlı option sınıfları yalnız altyapı: `IpRateLimitOptions`, `RedisSettings` (BuildingBlocks/Options), sıkıştırma opsiyonları.
- Mevcut yeniden kullanılabilir altyapı: BuildingBlocks `Redis` + `ICacheService`/`HybridCacheServiceBase` (`Infrastructure/Services/CacheService.cs:26`), SignalR hub `Presentation/API/Hubs/PublicCacheHub.cs` (public cache invalidation; **agent progress için tasarlanmadı**).
- Sonuç: model/embedding yapılandırması **sıfırdan** oluşturulacak; sağlayıcı seçimi (yerel Ollama vs bulut) kullanıcı kararıdır (§8). Anahtar sızıntısı riski yok — hiçbir anahtar config'de bulunmuyor.

## 5. Tarihçe: kaldırılmış AI agent servisi

- `codebase_docs/ai_agent_codebase.md` (1488 satır) eski bir "AI Agent Service v2.0.0" (FastAPI + LangChain + LangGraph + Ollama + ChromaDB + RabbitMQ, hexagonal) kodbase'ini belgeler. **Bu kod çalışma ağacında yok** — repoda hiçbir `.py` dosyası bulunamadı; `src/services` dizini mevcut değil.
- Git tarihi: `src/services/ai-agent-service` (176 dosya: `app/agent/simple_blog_agent.py`, `indexer.py`, `rag_chat_handler.py`…) ve `BlogApp.BuildingBlocks.Messaging` (Ai* integration event'leri) `9a452d8`'de eklendi; `3dbdef8` "feat: major refactor — remove AI agent service, consolidate migrations, add features" ile silindi (472 dosya, −41012 satır).
- `.claude/rules/building-blocks.md:11`: "Messaging modülü kaldırıldı (2026-04-07 — AI Agent + RabbitMQ bağımlılığı temizlendi). Yeniden eklenmesi gerekirse önceden dur ve mimari karar al."
- Ortak prompt'un 2. kuralı ("mevcut uygun bir agent paketi varsa onu genişlet") **karşılanamıyor: paket yok.** 3. kuralın önerdiği konum (`src/services/ai-agent-service/app/agent_core`) boş bir alan olarak yeni oluşturulacaktır — bu, A1 için belirli ve yeterli bir hedeftir. Eski kodun referans alınması ayrı bir mimari karardır (D001/D003 yeni çekirdek der); bu faz yalnız tespiti raporlar.

## 6. Frontend'te agent durumu

`src/frontend/blogapp-web/src` taramasında agent özelliği yok. Eşleşenler yalnız SEO/keşif metinleri: `app/layout.tsx:141` (`llms.txt` linki), `app/robots.ts:20-61` (GPTBot, ChatGPT-User, ClaudeBot, PerplexityBot… kuralları), `components/layout/ide-terminal.tsx:47,79` (dekoratif yazı), `lib/discovery-rewrites.ts:1` (`/llms.txt`, `/rss` yolları). Sonuç: A9/B9 UI işi sıfırdan başlar; bugün taşınacak/uzatılacak bir agent arayüzü yok.

## 7. İş modeli ayrımı — B1'in envelope'a eşleyeceği anlamlar

Plan A0'ın istediği "makale revizyonu, içerik hash'i, kaynak kimliği, çalışma kimliği" tanımları. Bunlar **iş modeli** anlamlarıdır; AMQP envelope'u bunların dışına eklenir (plan A1 kuralı).

1. **Makale revizyonu (`article_revision`)** — Bir makalenin yayımlanmış içeriğinin tek bir anlık görüntüsünü tanımlayan, backend tarafından atanan, makale başına monoton artan kimlik. Revizyon, içeriğin **ve** durumun (Published) birlikte geçerli olduğu dönemi işaretler; yayın kaldırma yeni bir revizyon uçlarıdır. ⚠️ Bugünkü `BlogPost.Version` (xmin rowversion) bu tanıma **uymaz**: opak, view-count artışında bile değişir, DTO'ya çıkmaz, geçmişsizdir. A1/B1'in revizyonun kaynağına karar vermesi gerekir (ör. `PostDetailQueryDto`'ya gerçek bir revision alanı eklenmesi veya snapshot tablosu) — bu bir kod değişikliğidir, A0 kapsamı dışında.
2. **İçerik hash'i (`article_content_hash`)** — Agent'a sunulan makale snapshot'ı içeriğinin (markdown `Content`'in UTF-8 baytlarının) SHA-256 özeti. Agent, gelen snapshot üzerinden hash'i yeniden hesaplayıp ExecutionContext'teki değerle eşleşmezse çalışmayı "bayat bağlam" hatasıyla reddeder. Bu, `IdempotencyRequestHasher`'daki komut idempotency hash'inden farklı amaçtır; karıştırılmamalıdır.
3. **Kaynak kimliği (`source_id`)** — Agent'ın `AgentOutcome.citations` içinde döndürdüğü, iddianın dayandığı içeriği tanımlayan referans: makale kaynaklı kanıt için `(article_id, article_revision, chunk_index)` üçlüsü; web kaynaklı kanıt için URL + erişim zamanı. `chunk_index` A3'teki bölümleme ile anlamlanır; bugün chunk üreten kod yok.
4. **Çalışma kimliği (`run_id`)** — Tek bir agent yürütmesinin backend'in ürettiği ve sahipliğini doğruladığı tekil kimliği (ana prompt: "Kimlik ve run sahipliği backend tarafından doğrulanır; istemci owner_id alanı yetki kaynağı değildir"). `conversation_id` kullanıcı oturumunu, `run_id` tek yürütmayı temsil eder; aynı konuşmanın yeniden denemesi yeni `run_id` alır. İptal/resume ve terminal sonuç tekrar bulunuşu `run_id`'ye bağlanır. Bunlar iş modeli alanlarıdır; queue/exchange/dead-letter gibi taşıma kavramları **değildir** (bkz. plan A1: "Mesajın kuyruğa alınması veya teslim edilmesi iş modeli durumu değildir").

## 8. Plan varsayımları ile kodun karşılaştırması — uymayanlar

| # | Plan varsayımı | Kod gerçeği | Etki |
| --- | --- | --- | --- |
| 1 | A1: EC `article_revision` + `article_content_hash` taşır | Kodda revizyon/hash kavramı yok; `Version` bir xmin concurrency token'ı (BlogPostConfiguration.cs:32-34), DTO'ya çıkmıyor | A1 öncesi revizyon kaynağına karar; hash agent tarafında snapshot'tan hesaplanabilir (backend alanı şart değil) |
| 2 | Ortak prompt kural 2: "mevcut uygun bir agent paketi varsa onu genişlet" | Paket yok; eskisi `3dbdef8`'de bilinçli silindi (§5) | A1 yeşil alan; eski kodun yeniden kullanımı ayrı karar |
| 3 | Ortak prompt kural 3: `src/services/ai-agent-service/app/agent_core` "değerlendir" | `src/services` yok, yeni oluşturulacak | Konum belirli; çözülmesi gereken engel değil |
| 4 | Profil tanıtımı + proje rehberi agent özelliği | Backend'de Profile/Project kaynağı yok; profil yalnız statik SEO/config (§3) | A1 `ProfileRepository`/`ProjectRepository` doldurulmadan veri kaynağı kararı gerekli |
| 5 | "Kullanılabilir model ve embedding ayarları" | Hiçbir model/embedding ayarı veya paketi yok (§4) | A2 öncesi model sağlayıcı kararı; konfigürasyon sıfırdan |
| 6 | İçerik "makale" olarak bölümleme/indeksleme (A3) | İçerik tek `string` ham markdown; bölümleme kodu yok | A3 chunking stratejisi yeni; `code fence` koruması markdown'a özel dikkat gerektirir |
| 7 | Haberleşme ayrı planda (D002) | `BuildingBlocks.Messaging` silindi; tekrar ekleme öncesi mimari kararı isteniyor (building-blocks.md:11) | B planı için kısıt; agent çalışma listesine taşınmadı (kabul ölçütü 3'ü korur) |

Uyan varsayımlar: içerik markdown'dır ve sanitization sınırı bellidir; yayımlanma durumu tek enum'da net; `Slug` üretim/çakışma davranışı bellidir; Redis/cache altyapısı mevcuttur; frontend'te beklenmedik agent kodu yoktur.

## 9. Kabul ölçütleri karşılama

1. **"Agent çekirdeğinin nereye ekleneceği ve hangi mevcut kodun kullanılacağı bellidir."** → **Karşılandı.** Konum: `src/services/ai-agent-service/app/agent_core` (ortak prompt kural 3). Kullanılacak mevcut kod ve karşılıkları `agent-architecture.md` §4-5'te port tablosuyla eşlendi (BlogPost okuma yolu, Slug VO, Result/Error düzeni, Redis cache altyapısı).
2. **"Her portun sağlayacağı veri ve hata türleri tanımlıdır."** → **Karşılandı.** 11 port için veri, hata türü (config, validation, not_found, stale_snapshot, budget_exhausted, cancelled, provider_error) ve mevcut-kod karşılığı `agent-architecture.md` §5 tablosunda.
3. **"Haberleşme bileşenleri agent çalışma listesine karışmamıştır."** → **Karşılandı.** RabbitMQ/envelope/consumer maddeleri bu rapor ve mimari belgesinde yalnız kısıt olarak geçer; B0/B1'e devredildi. (Burada haberleşme kodu önerilmedi; B0'ın işi.)
4. **"Sonraki aşamaların bağımlılıkları somut olarak gösterilmiştir."** → **Karşılandı.** `agent-architecture.md` §6 takip tablosunda her aşamanın girdi bağımlılığı yazılı; iki A1 öncesi karar §8'de somutlaştırıldı.

## 10. Açık kararlar (A1 öncesi ana orkestratöre)

1. **Revizyon kaynağı:** `article_revision`'ın üretileceği yer (DTO alanı eklemek mi, snapshot tablosu mu). A1 iş modeli buna muhtaç; A0 salt okunur olduğundan karar vermedi.
2. **Proje/profil veri kaynağı:** `ProfileRepository`/`ProjectRepository` portlarını besleyecek kaynak (backend config/seed mi, yeni feature mı, statik içerik mi).
3. **Model/embedding sağlayıcı:** Sağlayıcı ve konfigürasyon yeri; eski servisin Ollama tercihi rehber olabilir ama kararı D001/D006 çizgisinde kullanıcı/onay sürecine aittir.
4. **Eski agent kodunun rolü:** `3dbdef8`'de silinen `src/services/ai-agent-service` ve `codebase_docs/ai_agent_codebase.md` referans mı, çöp mü. (Öneri: ders olarak okunsun, kod tabanı olarak yeniden kurulmasın; gerekçe silme commit'inde zaten var.)

## 11. Kaynaklar (yalnız gerçekten gelen CONTEXT parçaları)

- [ENG-AGENTS#C1] workflow/agent ayrımı — mimari belgesindeki "çalışma deseni" bölümünün gerekçesi.
- [ENG-AGENTS#C2] routing/paralelleştirme/orchestrator-worker desenleri — A4 alt araştırma deseni notu.
- [ENG-CONTEXT#C1] bağlam seçimi/ilgili bilgiyi gerektiğinde getirme — ExecutionContext minimal taşıma ilkesi.
- [LG-WORKFLOWS#C2] orchestrator/Send API/paralel sonuçların ortak state'e birleşimi — A2/A4 bağımlılık notu.
- [PY-ASYNCIO#C1] TaskGroup yapılandırılmış eşzamanlılık (hata ve iptal birlikte) — paralel araştırma görevlerinin iptal davranışı notu.
- Repo kanıtı: yukarıda dosya/satır referanslı her madde; komut çıktıları §1'de.
