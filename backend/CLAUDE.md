# Backend (BlogApp.Server)

> Bu dosya `backend/` altinda calisirken otomatik yuklenir.
> Genel kurallar: `.claude/CLAUDE.md` + `.claude/rules/{architecture,backend,database}.md`.
> Burada **gercek envanter** + projeye ozgu sapmalar.

## 4 katman + bagimlilik yonu

| Proje | Bagimli oldugu | Anahtar paketler |
|---|---|---|
| `BlogApp.Core.Domain` | (yok — saf C#) | yok |
| `BlogApp.Core.Application` | Domain + BuildingBlocks | MediatR 14.0.0, AutoMapper 16.1.1, FluentValidation 12.1.1, BCrypt.Net-Next 4.0.3 |
| `BlogApp.Infrastructure` | Application + Domain + BuildingBlocks | EF Core 10.0.1, Npgsql 10.0.0, System.IdentityModel.Tokens.Jwt 8.15.0, HtmlSanitizer 9.0.892, SixLabors.ImageSharp 3.1.12 |
| `BlogApp.Presentation.Api` | Application + Infrastructure | JwtBearer 10.0.1, Asp.Versioning.Http 8.1.0, AspNetCoreRateLimit 5.0.0, Serilog.AspNetCore 10.0.0, OpenTelemetry.* 1.15.x, Swashbuckle 10.1.0, System.ServiceModel.Syndication 10.0.5 |

Bagimlilik **yalnizca yukaridan asagiya**. Domain hicbir seye bagli degil — `Domain.csproj`'da hicbir `<PackageReference>` veya `<ProjectReference>` yok.

## Komutlar

```bash
dotnet build BlogApp.sln
dotnet run --project backend/Presentation/API

# Migration (--project Infrastructure, --startup-project Api)
dotnet ef migrations add {Name} \
  --project backend/Infrastructure/Infrastructure \
  --startup-project backend/Presentation/API

dotnet ef database update \
  --project backend/Infrastructure/Infrastructure \
  --startup-project backend/Presentation/API
```

---

## Domain envanteri

**Base:** `BaseEntity` (`Id: Guid`) → `BaseAuditableEntity` (`CreatedAt`, `CreatedBy`, `UpdatedAt`, `UpdatedBy`, `IsDeleted`, `DeletedAt`).

**7 Entity** (`Domain/Entities/`):
- `BlogPost` — domain method'larli zengin entity: `Publish()`, `Archive()`, `Unpublish()`, `CalculateReadingTime()`, `GetExcerpt()`
- `User` — `FullName` computed
- `Category`, `Tag`, `Comment` — veri tasiyicilar
- `RefreshToken` — `IsExpired`/`IsRevoked`/`IsActive` computed; **`BaseEntity` inherit eder** (audit field'larini manuel tasir, security gerekcesi)
- `IdempotencyRecord` — request dedup

**2 Value Object** (`Domain/ValueObjects/`):
- `Slug` — TR karakter normalizasyonu + regex
- `Email` — `Create()` + `CreateOrDefault()` factory

**3 Enum:** `PostStatus` (Draft/Published/Archived), `UserRole` (Reader/Author/Editor/Admin), `IdempotencyRecordStatus` (Processing/Completed/Failed)

**5 Exception** (`Domain/Exceptions/`) — hepsi `DomainException` base'inden inherit. HTTP map'leri `.claude/rules/backend.md`'de.

**Domain Event:** YOK. (`Application/Common/Events/` klasoru bos.) Event'ler `INotificationHandler` ile yapilirsa Application'a koyulacak — Domain'e dokunma.

---

## Application envanteri

### Common/

| Klasor | Icerik |
|---|---|
| `Behaviors/` | `LoggingBehavior`, `CachingBehavior`, `ValidationBehavior`, `IdempotencyBehavior` (sira: **Logging → Caching → Validation → Idempotency**, degistirme) |
| `BusinessRuleEngine/` | `BusinessRuleEngine` — `Result` chain executor (sync + async). `IBusinessRule` ve `BusinessRuleException` YOK |
| `Constants/` | `AsyncOperationErrorCodes` |
| `Events/` | (bos) |
| `Interfaces/` | `IApplicationDbContext`, 12 repository interface (Read/Write x 6 aggregate), 3 repository base, `IUnitOfWork`, 10 service, `IIdempotentCommand` |
| `Models/` | `Result<T>`, `ApiResponse<T>` (+ `PaginationMeta`), `PaginatedList`, `IdempotencyModels` |
| `Options/` | `JwtSettings` (32+ byte secret validation), `AdminUserSettings`, `ServerLimitsSettings`, `SiteSettings` |
| `Security/` | `PostAuthorizationAction` |
| `Utilities/` | `IdempotencyRequestHasher`, `ImageValidation` |
| `Validators/` | `UrlValidationHelper` (FluentValidation request validator'lari **Features altinda**) |
| `SwrRefreshContext.cs` | `AsyncLocal<bool>` flag — SWR background refresh sirasinda `CachingBehavior`'i bypass eder; cache miss simulasyonu yapip handler'i direkt calistirir |

### 10 Service interface

`ICacheService`, `ICacheInvalidationNotifier`, `ICurrentUserService`, `IJwtTokenService`, `IIdempotencyService`, `IFileStorageService`, `IHtmlSanitizerService`, `IPostAuthorizationService`, `ITagService`, `ITokenBlacklistService`

### 5 Feature (`Features/`)

| Feature | Commands | Queries |
|---|---|---|
| `AuthFeature` | Login, Register, ChangePassword, RefreshToken, Logout, AdminResetPassword | GetCurrentUser |
| `PostFeature` | CreatePost, UpdatePost, DeletePost, PublishPost+Unpublish, SaveDraft | GetPostById, GetPostBySlug, GetPostsList, GetMyPosts |
| `CategoryFeature` | CreateCategory, UpdateCategory, DeleteCategory | GetAllCategory, GetByIdCategory |
| `TagFeature` | CreateTag, DeleteTag | GetAllTag, GetByIdTag |
| `MediaFeature` | UploadImage, UploadImages, DeleteMedia | — |

> **Not:** SEO endpoint'leri (`/sitemap.xml`, `/rss`) MediatR kullanmaz — `SeoEndpoints.cs` `IApplicationDbContext`'i direkt kullanir, eski `SeoFeature` klasoru kaldirildi (dead code).

Her feature klasor agaci icin: `.claude/rules/backend.md` "Feature folder structure".

### 4 BusinessRules class

`PostBusinessRules`, `CategoryBusinessRules`, `TagBusinessRules`, `AuthBusinessRules` — `Application/DependencyInjection.cs`'te `Scoped` register.

---

## Infrastructure envanteri

### Persistence/

- **`AppDbContext.cs`**: 7 DbSet (Posts, Categories, Tags, Users, Comments, RefreshTokens, IdempotencyRecords).
  - `OnModelCreating()` → `ApplyConfigurationsFromAssembly` + **global soft-delete `HasQueryFilter`'lari merkezi**, her entity icin tek tek (Configuration dosyalarinda DEGIL):
    ```csharp
    modelBuilder.Entity<BlogPost>().HasQueryFilter(p => !p.IsDeleted);
    // ... + RefreshToken ozel: r => r.User != null && !r.User.IsDeleted
    ```
  - `SaveChangesAsync()` → `ChangeTracker` ile audit otomatik (Added: `CreatedAt`+`UpdatedAt`, Modified: `UpdatedAt`).
- **`Configurations/`** (7 dosya): her entity icin Fluent API config (index, relationship, conversion). Soft-delete filter buraya **konulmaz** — yukaridaki merkezi yer kullanilir.
- **`Migrations/`**: tek konsolide migration `20260407130831_InitialCreate` (+ Designer + ModelSnapshot). `tasks/done.md`'de "consolidate migrations" maddesi varsa bu o.
- **`Seeders/DbSeeder.cs`**: idempotent admin user seed. Env var oncelikli (`ADMIN_EMAIL`/`ADMIN_PASSWORD`/`ADMIN_USERNAME`), appsettings fallback. **Hardcoded fallback YOK.** BCrypt workFactor=12.

### Repositories/ (12 specific + 3 generic)

```
EfCoreRepository<T>           # base
EfCoreReadRepository<T>       # base read
EfCoreWriteRepository<T>      # base write

EfCoreBlogPostReadRepository  / EfCoreBlogPostWriteRepository
EfCoreCategoryReadRepository  / EfCoreCategoryWriteRepository
EfCoreCommentReadRepository   / EfCoreCommentWriteRepository
EfCoreRefreshTokenReadRepo    / EfCoreRefreshTokenWriteRepository
EfCoreTagReadRepository       / EfCoreTagWriteRepository
EfCoreUserReadRepository      / EfCoreUserWriteRepository
```

`UnitOfWork.cs`: Lazy-init property'ler — `PostsRead`/`PostsWrite`, `CategoriesRead`/`CategoriesWrite`, `TagsRead`/`TagsWrite`, `UsersRead`/`UsersWrite`, `CommentsRead`/`CommentsWrite`, `RefreshTokensRead`/`RefreshTokensWrite`. `SaveChangesAsync`, iki overload `BeginTransactionAsync` (`(ct)` ve `(IsolationLevel, ct)` → `ITransactionScope`), `CommitTransactionAsync`, `RollbackTransactionAsync`, `ExecuteResilientAsync<T>`, `IAsyncDisposable + IDisposable`.

> Repository interface'leri `Application/Common/Interfaces/Persistence/{X}Repository/` alt klasorlerinde — `IUnitOfWork` ve `ITransactionScope` ise `Persistence/` ust seviyesinde.

### Services/ (11 impl)

| Service | Sorumluluk |
|---|---|
| `JwtTokenService` | HS256 token gen + custom claims + secure-random refresh token (base64) |
| `CurrentUserService` | `IHttpContextAccessor` + claims parser (userId / NameIdentifier fallback) |
| `FileStorageService` | Upload/delete (uploads/ dizini) |
| `CacheService` | `IBasicCacheService` + `IHybridCacheService` (BuildingBlocks.Caching uzerine) |
| `TokenBlacklistService` | Logout sonrasi token revoke + cache-backed lookup |
| `IdempotencyService` | DB-backed dedup (`OperationId` + `EndpointName` key) |
| `IdempotencyCleanupService` | HostedService — stale record temizler |
| `RefreshTokenCleanupService` | HostedService — expired token temizler |
| `TagService` | `GetOrCreateAsync` — tracked entity dondurur (PK_tags duplicate fix, bkz. son commit) |
| `HtmlSanitizerService` | XSS sanitization (singleton) |
| `PostAuthorizationService` | Post ownership check |

---

## Api envanteri

### Endpoints/ (7 dosya, ~39 endpoint)

| Dosya | Route prefix | Endpoint sayisi | Auth |
|---|---|---|---|
| `AuthEndpoints.cs` | `/api/v1/auth` | 7 | login/register public; geri kalan auth |
| `PostsEndpoints.cs` | `/api/v1/posts` | 14 | GET public, CUD `RequireAuthorization` |
| `CategoriesEndpoints.cs` | `/api/v1/categories` | 5 | CUD `RequireRole("Admin")`, R public |
| `TagsEndpoints.cs` | `/api/v1/tags` | 3 | CUD role-based, R public |
| `MediaEndpoints.cs` | `/api/v1/media` | 3 | `RequireRole("Admin","Editor","Author")` |
| `SeoEndpoints.cs` | `/api/v1/seo` | 6 | tum public (sitemap/robots/llms.txt/RSS) |
| `CsrfEndpoints.cs` | `/api/v1/csrf` | 1 | public token fetch |
| `IdempotencyEndpointHelper.cs` | (helper) | — | endpoint level idempotency wiring |

> **Not:** `SeoEndpoints` `IApplicationDbContext`'i **direkt** kullanir (sitemap/RSS icin statik query). Diger endpoint'ler MediatR `ISender` uzerinden gider — bunu standartdan sapma sebebi: SEO content genelde no-mutation, no-business-rule.

### Middlewares/ (4)

`ExceptionHandlingMiddleware`, `RequestLoggingMiddleware`, `SecurityHeadersMiddleware`, `SignalRConnectionLimitMiddleware`

### Filters/ (1)

`AntiforgeryValidationFilter` — endpoint filter (`AddEndpointFilter`), CSRF validation SPA icin (`X-CSRF-TOKEN` header).

### Helpers/ (4)

`CookieHelper` (auth cookie set/IP), `CsrfHelper`, `IdempotencyHelper` (header → operationId), `MediaValidationHelper`.

### Hubs/ (1)

`PublicCacheHub` — `SubscribeToGroup(name)` + `UnsubscribeFromGroup(name)`. **Whitelist:** `["posts", "categories", "tags"]`. Broadcast trigger: `CacheInvalidationNotifier`.

### Services/ (1)

`CacheInvalidationNotifier` — `IHubContext<PublicCacheHub>` + `IOutputCacheStore`. `NotifyGroupInvalidatedAsync`/`NotifyKeyRemovedAsync`/`NotifyPrefixRemovedAsync`.

### Extensions/ (8)

`AuthenticationExtensions` (JWT + cookie fallback + JTI invalidation), `SecurityExtensions` (Antiforgery + IpRateLimiting), `CorsExtensions`, `CachingExtensions` (OutputCache policies + Brotli/Gzip), `SwaggerExtensions` (versioning), `ObservabilityExtensions` (Serilog + OTel + HealthChecks), `RegisterEndpointsExtensions` (`RegisterAllEndpoints()`), `ClaimsPrincipalExtensions`.

### Program.cs middleware sirasi (143 satir)

```
UseSwaggerInDevelopment → UseForwardedHeaders (ALB/nginx) → UseSecurityHeaders →
UseExceptionHandling → UseRequestLogging → UseResponseCompression →
UseMiddleware<SignalRConnectionLimitMiddleware> → UseHsts (prod) →
UseStaticFiles (/uploads) → UseCors("AllowFrontend") → UseIpRateLimiting →
UseAuthentication → UseAuthorization → UseOutputCache → UseAntiforgery →
RegisterAllEndpoints → MapHealthChecks("/health", InternalHosts) →
MapHub<PublicCacheHub>("/hubs/public-cache") → MapPrometheusScrapingEndpoint
```

Migration auto-run: prod (`Database__RunMigrationsOnStartup=true`). Seed: dev only.

### appsettings ust seviye section'lari

`Logging`, `Serilog`, `ConnectionStrings` (DefaultConnection + Redis), `JwtSettings` (Secret/Issuer/Audience/ExpirationMinutes — prod 20dk / dev 60dk), `AdminUser`, `CorsOrigins`, `IpRateLimiting` (login 5/min, register 10/h, upload 10/min, refresh 10/min, change-password 5/h, global 300/min+3000/h), `ServerLimits` (50MB body, SignalR timeout, OutputCache dakikalari).

---

## Anahtar gotcha'lar (gercek koddan)

1. **`HasQueryFilter` AppDbContext.OnModelCreating'de merkezi** — `Configuration/` dosyalarina ekleme.
2. **`RefreshToken` filter ozel:** `r => r.User != null && !r.User.IsDeleted` (User soft-delete olunca token da gizlenir).
3. **`IIdempotentCommand`** (`IIdempotentRequest` DEGIL) — 3 field: `OperationId`, `IdempotencyEndpointName`, `CustomRequestHash?`.
4. **`DomainException` → 400** (rules eskiden 422 diyordu, gercek middleware 400).
5. **`ConflictException` → 409** — state/uniqueness ihlali icin (uniq slug, vb.).
6. **Repository Read/Write ayri** — query handler `IBlogPostReadRepository`, command handler `IBlogPostWriteRepository`. `IUnitOfWork` ikisini de exposes eder.
7. **Tek migration:** `20260407130831_InitialCreate`. Yeni migration eklerken bu konsolidasyon kararini koru.
8. **`SwrRefreshContext`** — SWR background refresh re-entry koruyucusu (`AsyncLocal` flag). Cache invalidation pipeline'inda bypass yapar; dokunmadan once ne yaptigini oku (memory: `swr_cache_bug.md`).
9. **2 HostedService:** `IdempotencyCleanupService` + `RefreshTokenCleanupService` — DI'da `Singleton` register, kapatma yok.
10. **SeoEndpoints `IApplicationDbContext` direkt enjekte ediyor** — diger 6 endpoint dosyasi MediatR `ISender` kullanir. Yeni endpoint yazarken ISender tercih.
11. **Layered error handling (post 2026-05-01 refactor):** Domain invariant ihlalinde throw, Application handler `Result<TInner>.Failure(Error.X(...))` doner — wrapper response tipleri **kaldirildi**. `IRequestHandler<TReq, Result<TInner>>` standart. Void operation icin `Result<Unit>` (MediatR `Unit.Value`). Endpoint `response.ToHttpResult()` ile category-driven HTTP status. `Error` factory'leri: `NotFound/Conflict/Forbidden/Unauthorized/Validation/Domain` (`Application/Common/Errors/`). ValidationBehavior throw etmez — Result.Failure doner. Detay: `.claude/rules/backend.md` "Layered error handling".
12. **Archive endpoint = Unpublish handler:** `/api/v1/posts/{id}/archive` aslinda `UnpublishPostCommandRequest` gonderir (alias). Eskiden ayri `ArchivePostCommand` klasoru vardi, kaldirildi.
13. **Test infrastructure not:** `tests/BlogApp.Presentation.Api.Tests` icindeki 3 eski test dosyasi `*.cs.disabled` rename edildi (kaldirilmis Messaging modulune referans veriyordu). FluentAssertions 6.12.2 + xUnit 2.9.3 ile yeni testler yaziliyor.
