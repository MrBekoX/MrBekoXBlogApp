# BuildingBlocks

> Bu dosya `src/BlogApp.BuildingBlocks/` altinda calisirken otomatik yuklenir.
> Detayli kurallar: `.claude/rules/building-blocks.md`.
> Burada yalnizca bu agacin kapsamina ozgu olanlar var.

## Mevcut moduller

| Modul | Klasor | Sorumluluk |
|---|---|---|
| Caching | `BlogApp.BuildingBlocks.Caching/` | L1 (in-memory) + L2 (Redis) hybrid cache |

> NOT: `Messaging` modulu 2026-04-07'de kaldirildi (AI Agent + RabbitMQ temizligi). Yeniden eklemeden once dur ve mimari karar al.

## Caching ic yapisi

```
Abstractions/         # IBasicCacheService, IHybridCacheService, ICacheableQuery
Services/             # HybridCacheServiceBase + concrete impl
Redis/                # Redis-specific helper'lar
Options/              # CacheOptions (TTL, key prefix, vb.)
Metrics/              # OpenTelemetry counter/histogram
Extensions/           # IServiceCollection.AddBlogAppCaching(...) gibi
DependencyInjection.cs
```

## Ana kural — UYULMASI ZORUNLU

- Application/Infrastructure'dan **`IDistributedCache` veya `IMemoryCache` direkt enjekte ETME**.
  Hep `IBasicCacheService` veya `IHybridCacheService` uzerinden git.
- Yeni cache servis impl'i: `HybridCacheServiceBase`'i extend et, sifirdan yazma.
- Cache key konvansiyonu: `{aggregate}:{id}:{version}` — versiyon invalidation icin sart.
- `CachingBehavior` (Application'da) sadece `ICacheableQuery` implement eden Query'lerde calisir.

## BuildingBlock olma sarti

Yeni modul eklemek istiyorsan **once dur ve sor**:

1. Gercekten **>=2 yerden** kullanilacak cross-cutting concern mi?
2. Domain'e bagimsiz mi (BuildingBlock domain bilmez)?
3. Stateful global state tasimiyor mu?
4. Business logic icermiyor mu (sadece teknik altyapi)?

Birine "hayir" diyorsan: BuildingBlock degil, Application veya Infrastructure'a ait.

## Yeni modul ekleme akisi

1. Klasor: `BlogApp.BuildingBlocks.{X}/`
2. `BlogApp.sln`'e ekle.
3. Tuketici .csproj'lara `<ProjectReference>` ekle.
4. Standart icerik: `Abstractions/I{X}Service.cs`, `Services/{X}Service.cs`, `DependencyInjection.cs` (`services.Add{X}()`).
5. Domain'e bagimlilik EKLEME.
6. `.claude/rules/building-blocks.md`'ye ve bu dosyaya entry ekle.

## Aday ama gereksiz

| Aday | Neden gereksiz |
|---|---|
| Logging | Serilog + `ILogger<T>` zaten yeterli |
| RateLimiting | `AspNetCoreRateLimit` paketi yetiyor |
| Idempotency | `IdempotencyBehavior` (Application) + record (Infrastructure) yeterli |
