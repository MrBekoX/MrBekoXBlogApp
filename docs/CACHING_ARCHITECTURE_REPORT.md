# BlogApp Caching Mimarisi Raporu

**Tarih:** 2026-02-01
**Analiz Edilen Projeler:** BlogApp.Server, BlogApp.BuildingBlocks
**Rapor Sürümü:** 1.0

---

## Özet

Bu rapor, BlogApp çözümünde implemente edilen caching mimarisinin kapsamlı bir analizini sunmaktadır. Sistem **hibrit L1/L2 caching stratejisi** ile **Stale-While-Revalidate (SWR)** desenini kullanmakta, SignalR üzerinden gerçek zamanlı cache invalidasyon ve OpenTelemetry metrikleri ile kapsamlı gözlemlenebilirlik sunmaktadır.

### Temel Özellikler

- ✅ **Hibrit Caching**: L1 (in-memory) + L2 (Redis) iki katmanlı mimari
- ✅ **SWR Deseni**: Optimum performans için modern stale-while-revalidate
- ✅ **Gerçek Zamanlı Invalidation**: SignalR tabanlı frontend bildirimleri
- ✅ **Kapsamlı Metrikler**: OpenTelemetry tabanlı gözlemlenebilirlik
- ✅ **Graceful Degradation**: Redis kullanılamazken in-memory fallback
- ⚠️ **İyileştirme Alanları**: Bellek sızıntısı riskleri, SCAN performans optimizasyonu

---

## 1. Mimari Genel Bakış

### 1.1 Bileşen Diyagramı

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Application Katmanı                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────────┐    ┌──────────────────┐                       │
│  │ MediatR Sorgular │───>│ CachingBehavior  │                       │
│  │ (ICacheableQuery)│    │ (Pipeline)       │                       │
│  └──────────────────┘    └────────┬─────────┘                       │
│                                   │                                  │
│                          ┌────────▼─────────┐                        │
│                          │  ICacheService   │                        │
│                          │ (Hybrid L1/L2)   │                        │
│                          └────────┬─────────┘                        │
│                                   │                                  │
│  ┌──────────────────┐    ┌────────▼─────────┐                        │
│  │ Command Handler' │───>│ Cache Invalidation│                       │
│  │ (Write İşlemleri)│    │   (Remove/Version)│                       │
│  └──────────────────┘    └────────┬─────────┘                        │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Infrastructure Katmanı                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              HybridCacheServiceBase                          │   │
│  │  ┌─────────────────┐         ┌─────────────────┐            │   │
│  │  │  L1 Cache       │         │  L2 Cache       │            │   │
│  │  │  (IMemory)      │◄───────►│  (Redis)        │            │   │
│  │  │  TTL: 30sn      │  Promote│  TTL: 5dk       │            │   │
│  │  └─────────────────┘         └─────────────────┘            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              CacheStampedeProtection                          │   │
│  │         (Anahtar başına semaphore tabanlı kilitler)           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend Katmanı                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │           CacheInvalidationHub (SignalR)                     │    │
│  │           - Invalidation olaylarını yayınla                  │    │
│  │           - İstemci abonelik yönetimi                         │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │           use-cache-sync Hook (React)                       │    │
│  │           - Invalidation olaylarını dinle                    │    │
│  │           - Yerel state güncelle                             │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Teknoloji Yığını

| Bileşen | Teknoloji | Amaç |
|---------|-----------|------|
| **L1 Cache** | `IMemoryCache` (Microsoft) | In-memory caching, çok hızlı erişim |
| **L2 Cache** | `StackExchange.Redis` | Dağıtık caching, cross-instance paylaşım |
| **Gerçek Zamanlı** | `SignalR` | Cache invalidation bildirimleri |
| **Metrikler** | `OpenTelemetry` | Gözlemlenebilirlik ve monitoring |
| **Pipeline** | `MediatR` | Pipeline behavior'ları ile caching |

---

## 2. Temel Bileşenler

### 2.1 Cache Servis Hiyerarşisi

```
IBasicCacheService (Get/Set/Remove)
       ▲
       │
IHybridCacheService (L1/L2 + SWR + Gruplar)
       ▲
       │
   ICacheService (Domain-specific + Bildirimler)
       ▲
       │
   CacheService (Implementasyon)
```

#### Dosya Konumları

| Interface/Sınıf | Path | Amaç |
|----------------|------|------|
| `IBasicCacheService` | `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Abstractions/IBasicCacheService.cs` | Temel cache operasyonları |
| `IHybridCacheService` | `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Abstractions/IHybridCacheService.cs` | Gelişmiş hibrit caching |
| `ICacheService` | `src/BlogApp.Server/BlogApp.Server.Application/Common/Interfaces/Services/ICacheService.cs` | Domain cache servisi |
| `HybridCacheServiceBase` | `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Services/HybridCacheServiceBase.cs` | Base implementasyon |
| `CacheService` | `src/BlogApp.Server/BlogApp.Server.Infrastructure/Services/CacheService.cs` | Domain implementasyonu |
| `BasicRedisCacheService` | `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Redis/BasicRedisCacheService.cs` | Basit Redis implementasyonu |

### 2.2 CachingBehavior (MediatR Pipeline)

**Konum:** `src/BlogApp.Server/BlogApp.Server.Application/Common/Behaviors/CachingBehavior.cs`

**Amaç:** `ICacheableQuery` interface'ini implemente eden her sorguyu otomatik olarak cache'ler

```csharp
public interface ICacheableQuery
{
    string CacheKey { get; }
    string CacheGroup { get; }
    TimeSpan CacheDuration { get; }
    bool UseStaleWhileRevalidate { get; }
    double SwrSoftRatio { get; } // Yumuşak/katı expiration oranı
}
```

**Çalışma Akışı:**
1. Request'in `ICacheableQuery` implemente edip etmediğini kontrol et
2. Cache'ten almaya çalış (L1 → L2)
3. Cache miss durumunda: handler'ı çalıştır, sonucu cache'le
4. SWR enabled ise: stale veriyi döndür, background refresh tetikle

### 2.3 CacheInvalidationNotifier (SignalR)

**Konum:** `src/BlogApp.Server/BlogApp.Server.Api/Services/CacheInvalidationNotifier.cs`

**Amaç:** Cache invalidation olaylarını bağlı frontend istemcilerine yayınla

**Metodlar:**
- `NotifyCacheInvalidatedAsync(cacheKey)` - Tek anahtar invalidasyon bildirimi
- `NotifyGroupInvalidatedAsync(groupName)` - Grup versiyonu rotasyon bildirimi

**Hub:** `/hubs/cacheinvalidation` endpoint'inde `CacheInvalidationHub`

---

## 3. Caching Desenleri ve Stratejileri

### 3.1 Hibrit L1/L2 Caching

| Katman | Tip | TTL | Amaç |
|-------|-----|-----|------|
| **L1** | In-Memory (instance başına) | max 30sn | Ultra hızlı erişim |
| **L2** | Redis (dağıtık) | varsayılan 5 dk | Cross-instance paylaşım |

**Okuma Stratejisi:**
```
İstek → L1 Kontrol → Hit? Döndür
              ↓ Miss
            L2 Kontrol → Hit? L1'e promote et → Döndür
              ↓ Miss
            Factory Çalıştır → L1+L2'ye yaz → Döndür
```

**Yazma Stratejisi:**
```
Yaz → L1'e yaz (TTL: L2/10, min 10sn, max 2dk)
      → L2'ye yaz (tam TTL)
      → Temizlik için metadata takibi
```

### 3.2 Stale-While-Revalidate (SWR)

**Konsept:** Stale veriyi hemen döndürürken arka planda yeniler

**Konfigürasyon:**
```csharp
public GetPostsListQueryRequest : ICacheableQuery
{
    public TimeSpan CacheDuration = TimeSpan.FromMinutes(5);
    public bool UseStaleWhileRevalidate = true;
    public double SwrSoftRatio = 0.8; // TTL'nin %80'i soft expiration için
}
```

**Zaman Çizelgesi:**
```
Taze: 0 ile 4 dakika arası (5 dakikanın %80'i)
  ↓
Yumuşak Stale: 4 ile 5 dakika arası (stale döndür, background refresh tetikle)
  ↓
Katı Stale: 5+ dakika (cache miss, factory çalıştır)
```

**Faydaları:**
- Her zaman hızlı response (refresh bekleme yok)
- Background refresh veriyi makul derecede taze tutar
- Veritabanı üzerindeki yükü azaltır

### 3.3 Cache Versiyonlama (Grup Bazlı Invalidation)

**Konsept:** İlgili tüm cache anahtarlarını invalid etmek için grup versiyonunu döndür

**Anahtar Formatı:** `{grup}:v{versiyon}:{anahtarSoneki}`

**Örnek:**
```
posts:v1:slug:hello-world
posts:v1:list:sayfa-1
posts:v1:list:sayfa-2
```

v2'ye versiyon rotasyonundan sonra, tüm v1 anahtarları invalid olur:
```
posts:v2:slug:hello-world (yeni)
posts:v1:slug:hello-world (yetim, doğal olarak expires olur)
```

**Command'larda Kullanımı:**
```csharp
// Post güncellemesinden sonra
await _cacheService.RemoveAsync(PostCacheKeys.ById(postId));
await _cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug));
await _cacheService.RotateGroupVersionAsync(PostCacheKeys.Group);
await _invalidationNotifier.NotifyGroupInvalidatedAsync(PostCacheKeys.Group);
```

### 3.4 Cache Stampede Koruması

**Problem:** Aynı uncached anahtar için birden fazla eşzamanlı istek

**Çözüm:** Anahtar başına semaphore tabanlı kilitleme

**Implementasyon:**
```csharp
private readonly ConcurrentDictionary<string, SemaphoreSlim> _locks = new();

public async Task<T> GetOrSetAsync<T>(string key, Factory factory)
{
    var semaphore = _locks.GetOrAdd(key, _ => new SemaphoreSlim(1, 1));

    await semaphore.WaitAsync(TimeSpan.FromSeconds(5));
    try
    {
        // Double-check pattern
        var cached = await GetAsync<T>(key);
        if (cached.HasValue) return cached.Value;

        // Factory çalıştır (kilit koruması altında)
        var value = await factory();
        await SetAsync(key, value);
        return value;
    }
    finally
    {
        semaphore.Release();
        // Kullanılmayan lock'ları temizle
    }
}
```

### 3.5 Prefix Bazlı Invalidation

**Amaç:** Bir prefix ile eşleşen tüm anahtarları toplu olarak sil

**Implementasyon:** Dağıtık senaryolar için Redis SCAN kullanır

```csharp
public async Task RemoveByPrefixAsync(string prefix)
{
    // In-memory: iterate ve remove
    foreach (var key in _l1Keys.Where(k => k.StartsWith(prefix)))
    {
        _l1Cache.Remove(key);
    }

    // Redis: SCAN kullan (büyük verisetleri için cursor ile)
    var db = _connection.GetDatabase();
    var server = _connection.GetServer(...);
    foreach (var key in server.Keys(pattern: $"{prefix}*"))
    {
        await db.KeyDeleteAsync(key);
    }
}
```

---

## 4. Cache Anahtar Yönetimi

### 4.1 Cache Anahtar Yapısı

**Hiyerarşik Pattern:** `{grup}:{altgrup}:{tanımlayıcı}`

**Örnekler:**
```
posts:by-id:123
posts:by-slug:hello-world
posts:list:sayfa-1:sort-desc
categories:by-id:5
tags:all
```

### 4.2 Cache Anahtar Sabitleri

**Konum:** `src/BlogApp.Server/BlogApp.Server.Application/Features/*/Constants/*CacheKeys.cs`

**Posts:** `PostCacheKeys.cs`
```csharp
public static class PostCacheKeys
{
    public const string Group = "posts";

    public static string ById(Guid id) => $"{Group}:by-id:{id}";
    public static string BySlug(string slug) => $"{Group}:by-slug:{slug}";
    public static string List(int page, string sort) => $"{Group}:list:sayfa-{page}:sort-{sort}";
}
```

**Categories:** `CategoryCacheKeys.cs`
```csharp
public static class CategoryCacheKeys
{
    public const string Group = "categories";

    public static string ById(Guid id) => $"{Group}:by-id:{id}";
    public static string All = $"{Group}:all";
}
```

**Tags:** `TagCacheKeys.cs`
```csharp
public static class TagCacheKeys
{
    public const string Group = "tags";

    public static string ById(Guid id) => $"{Group}:by-id:{id}";
    public static string All = $"{Group}:all";
}
```

### 4.3 Cache Anahtar Extension'ları

**Konum:** `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Extensions/CacheKeyExtensions.cs`

**Utility Metodlar:**
```csharp
public static class CacheKeyExtensions
{
    // Metrikler için prefix çıkar
    public static string GetKeyPrefix(this string cacheKey);

    // Versiyonlu anahtar oluştur
    public static string ToVersionedKey(this string key, string group, long version);

    // Segmentlerden anahtar oluştur
    public static string ToCacheKey(this string prefix, params string[] segments);
}
```

---

## 5. Konfigürasyon ve Kurulum

### 5.1 Redis Konfigürasyonu

**appsettings.json:**
```json
{
  "Redis": {
    "Enabled": true,
    "ConnectionString": "localhost:6789",
    "InstanceName": "BlogApp:"
  }
}
```

**Kayıt:** `src/BlogApp.Server/BlogApp.Server.Infrastructure/DependencyInjection.cs`
```csharp
var redisSettings = configuration.GetSection(RedisSettings.SectionName).Get<RedisSettings>();

if (redisSettings?.Enabled == true && !string.IsNullOrEmpty(redisConnectionString))
{
    // Retry policy ile Redis
    services.AddSingleton<IConnectionMultiplexer>(_ =>
        ConnectionMultiplexer.Connect(options));

    services.AddStackExchangeRedisCache(opts =>
    {
        opts.Configuration = redisConnectionString;
        opts.InstanceName = redisSettings.InstanceName;
    });
}
else
{
    // In-memory fallback
    services.AddDistributedMemoryCache();
}
```

### 5.2 Servis Kaydı

**Infrastructure Katmanı:**
```csharp
// Tüm interface'ler aynı CacheService instance'ına çözülür
services.AddScoped<ICacheService, CacheService>();
services.AddScoped<IHybridCacheService>(sp => sp.GetRequiredService<ICacheService>());
services.AddScoped<IBasicCacheService>(sp => sp.GetRequiredService<ICacheService>());
```

**BuildingBlocks Katmanı:**
```csharp
// Temel caching
services.AddBasicCachingServices(configuration);

// Hibrit caching infrastructure
services.AddHybridCachingInfrastructure(configuration, meterName: "BlogApp.Cache");
```

### 5.3 Pipeline Kaydı

**Konum:** `src/BlogApp.Server/BlogApp.Server.Application/DependencyInjection.cs`

```csharp
// Sıra önemli!
services.AddTransient(typeof(IPipelineBehavior<,>), typeof(LoggingBehavior<,>));      // 1st
services.AddTransient(typeof(IPipelineBehavior<,>), typeof(CachingBehavior<,>));     // 2nd
services.AddTransient(typeof(IPipelineBehavior<,>), typeof(ValidationBehavior<,>));  // 3rd
```

**Çalışma Sırası:**
1. Logging (request başlangıcını logla)
2. Caching (cache kontrol et, hit ise döndür)
3. Validation (cache miss ise validate et)
4. Handler (cache miss ise çalıştır)

---

## 6. Kullanım Örnekleri

### 6.1 Cacheable Query (Okuma)

**Konum:** `src/BlogApp.Server/BlogApp.Server.Application/Features/PostFeature/Queries/GetPostsListQuery/GetPostsListQueryRequest.cs`

```csharp
public class GetPostsListQueryRequest : ICacheableQuery
{
    public int PageNumber { get; set; } = 1;
    public int PageSize { get; set; } = 10;

    // Cache konfigürasyonu
    public string CacheKey => PostCacheKeys.List(PageNumber, "desc");
    public string CacheGroup => PostCacheKeys.Group;
    public TimeSpan CacheDuration => TimeSpan.FromMinutes(5);
    public bool UseStaleWhileRevalidate => true;
    public double SwrSoftRatio => 0.8; // 4 dk soft, 5 dk hard
}

public class GetPostsListQueryHandler : IRequestHandler<GetPostsListQueryRequest, GetPostsListQueryResponse>
{
    public async Task<GetPostsListQueryResponse> Handle(GetPostsListQueryRequest request, CancellationToken ct)
    {
        // Bu CachingBehavior tarafından wrap edilir
        var posts = await _postReadRepository.GetPagedAsync(...);
        return new GetPostsListQueryResponse { Posts = posts };
    }
}
```

**Çalışma Akışı:**
```
İstemci İsteği
    ↓
CachingBehavior.CheckCache()
    ↓ L1 miss
L2 Cache Kontrol
    ↓ L2 miss (soft TTL içinde)
Handler Çalıştır (DB Sorgusu)
    ↓
L1'e (30sn) + L2'ye (5dk) yaz
    ↓
Response Döndür
```

### 6.2 Cache Invalidation (Yazma)

**Konum:** `src/BlogApp.Server/BlogApp.Server.Application/Features/PostFeature/Commands/UpdatePostCommand/UpdatePostCommandHandler.cs`

```csharp
public class UpdatePostCommandHandler : IRequestHandler<UpdatePostCommandRequest, UpdatePostCommandResponse>
{
    public async Task<UpdatePostCommandResponse> Handle(UpdatePostCommandRequest request, CancellationToken ct)
    {
        // 1. Entity güncelle
        var post = await _postWriteRepository.UpdateAsync(...);
        await _unitOfWork.SaveChangesAsync(ct);

        // 2. Belirli anahtarları invalid et
        await _cacheService.RemoveAsync(PostCacheKeys.ById(post.Id));
        await _cacheService.RemoveAsync(PostCacheKeys.BySlug(post.Slug));

        // 3. Grup versiyonunu döndür (tüm list sorgularını invalid eder)
        await _cacheService.RotateGroupVersionAsync(PostCacheKeys.Group);

        // 4. Frontend istemcilerine bildir
        await _invalidationNotifier.NotifyCacheInvalidatedAsync(PostCacheKeys.ById(post.Id));
        await _invalidationNotifier.NotifyGroupInvalidatedAsync(PostCacheKeys.Group);

        return new UpdatePostCommandResponse { Success = true };
    }
}
```

**Çalışma Akışı:**
```
İstemci İsteği (Post Güncelle)
    ↓
Veritabanını Güncelle
    ↓
L1 + L2'den kaldır (by-id, by-slug)
    ↓
Grup Versiyonunu Döndür (posts:v1 → posts:v2)
    ↓
SignalR Broadcast → Tüm bağlı istemciler
    ↓
Frontend: Yerel state güncelle (cache'ten kaldır)
    ↓
Response Döndür
```

### 6.3 Frontend Cache Senkronizasyonu

**Konum:** `src/blogapp-web/src/hooks/use-cache-sync.ts`

```typescript
export function useCacheSync() {
  useEffect(() => {
    const connection = new HubConnectionBuilder()
      .withUrl('/hubs/cacheinvalidation')
      .build();

    connection.on('CacheInvalidated', (cacheKey) => {
      // Yerel cache'ten kaldır
      queryClient.invalidateQueries([cacheKey]);
    });

    connection.on('GroupInvalidated', (groupName) => {
      // Bu grup için tüm sorguları invalid et
      queryClient.invalidateQueries([groupName]);
    });

    connection.start();
  }, []);
}
```

---

## 7. Metrikler ve Gözlemlenebilirlik

### 7.1 CacheMetrics

**Konum:** `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Metrics/CacheMetrics.cs`

**Toplanan Metrikler:**

| Metrik | Tip | Açıklama |
|--------|-----|----------|
| `cache.l1.hits` | Counter | L1 cache hit'leri |
| `cache.l1.misses` | Counter | L1 cache miss'leri |
| `cache.l2.hits` | Counter | L2 cache hit'leri |
| `cache.l2.misses` | Counter | L2 cache miss'leri |
| `cache.swr.stale` | Counter | Stale veri sunumu (SWR) |
| `cache.swr.refresh` | Counter | Tetiklenen background refresh'ler |
| `cache.operations.duration` | Histogram | Operasyon süresi (operasyon tipine göre) |
| `cache.active_locks` | Gauge | Aktif stampede lock'ları |
| `cache.tracked_keys` | Gauge | Takip edilen cache anahtarı sayısı |

**Dashboard Örneği (Prometheus):**
```
# L1 Hit Rate
sum(rate(cache_l1_hits_total[5m])) / sum(rate(cache_l1_hits_total[5m]) + rate(cache_l1_misses_total[5m]))

# L2 Hit Rate
sum(rate(cache_l2_hits_total[5m])) / sum(rate(cache_l2_hits_total[5m]) + rate(cache_l2_misses_total[5m]))

# SWR Effectiveness
sum(rate(cache_swr_stale_total[5m])) / sum(rate(cache_requests_total[5m]))
```

### 7.2 Monitoring Önerileri

1. **Yüksek Cache Miss Rate Alarmı:**
   - Eşik: 5 dakika boyunca > %50 miss oranı
   - Aksiyon: Cache anahtarı tasarımı veya TTL ayarlarını incele

2. **Yüksek L2 Miss Rate Alarmı:**
   - Eşik: > %30 L2 miss oranı
   - Aksiyon: L1 TTL'sini artırmayı veya cache warming'i düşün

3. **Stampede Lock'ları İzle:**
   - Metrik: `cache_active_locks` sürekli yüksek
   - Aksiyon: Cache süresini artır veya cache warming'i iyileştir

4. **SWR Refresh Success'ini Takip Et:**
   - Metrik: `cache_swr_refresh_total` vs hatalar
   - Aksiyon: Background refresh hatalarını incele

---

## 8. Tespit Edilen Sorunlar ve Öneriler

### 8.1 Kritik Sorunlar

#### Sorun 1: Bellek Sızıntısı Riski ⚠️

**Konum:** `HybridCacheServiceBase._keyExpirations`

**Problem:** Dictionary sürekli büyür, temizlenmez

```csharp
private readonly ConcurrentDictionary<string, DateTime> _keyExpirations = new();
```

**Etki:** Zamanla bellek kullanımı artar

**Öneri:**
```csharp
// Periyodik temizlik ekle
private readonly Timer _cleanupTimer;

public HybridCacheServiceBase()
{
    _cleanupTimer = new Timer(_ =>
    {
        CleanupExpiredKeys();
    }, null, TimeSpan.FromMinutes(5), TimeSpan.FromMinutes(5));
}

private void CleanupExpiredKeys()
{
    var now = DateTime.UtcNow;
    foreach (var key in _keyExpirations.Where(kvp => kvp.Value < now).Select(kvp => kvp.Key))
    {
        _keyExpirations.TryRemove(key, out _);
    }
}
```

#### Sorun 2: Redis SCAN Performansı ⚠️

**Konum:** `HybridCacheServiceBase.RemoveByPrefixRedisAsync()`

**Problem:** Redis SCAN milyonlarca anahtar varsa yavaş olabilir

**Etki:** Bulk operasyonlar için gecikmeli cache invalidation

**Öneri:**
- İlgili anahtarlar için prefix matching yerine Redis Hash kullan
- Daha iyi cursor handling ile batch silme implement et
- Prefix başına anahtarları takip etmek için Redis Sets kullanmayı düşün

```csharp
// Alternatif: Redis Sets kullan
public async Task TrackKeyAsync(string prefix, string key)
{
    var db = _connection.GetDatabase();
    await db.SetAddAsync($"prefix:{prefix}", key);
}

public async Task RemoveByPrefixAsync(string prefix)
{
    var db = _connection.GetDatabase();
    var keys = await db.SetMembersAsync($"prefix:{prefix}");
    await db.KeyDeleteAsync(keys);
    await db.KeyDeleteAsync($"prefix:{prefix}");
}
```

### 8.2 Orta Öncelikli Sorunlar

#### Sorun 3: Sessiz SignalR Hataları

**Konum:** `CacheInvalidationNotifier`

**Problem:** Bildirim hataları sessiz, frontend stale kalabilir

**Öneri:**
```csharp
public async Task NotifyCacheInvalidatedAsync(string cacheKey)
{
    try
    {
        await _hub.Clients.All.SendAsync("CacheInvalidated", cacheKey);
    }
    catch (Exception ex)
    {
        _logger.LogError(ex, "{CacheKey} için cache invalidation bildirimi başarısız", cacheKey);
        // Retry kuyruğuna veya dead letter queue'ya ekle
        await _failureQueue.EnqueueAsync(cacheKey);
    }
}
```

#### Sorun 4: Lock Timeout Handling

**Konum:** `HybridCacheServiceBase.GetOrSetAsync()`

**Problem:** Lock timeout olduğunda factory korumasız çalışır

**Öneri:**
- Tekrarlayan timeout'lar için circuit breaker ekle
- Retries için exponential backoff implement et
- Timeout olaylarını logla (monitoring için)

```csharp
if (!await semaphore.WaitAsync(TimeSpan.FromSeconds(5)))
{
    _logger.LogWarning("{CacheKey} için cache lock timeout", key);
    _metrics.IncrementLockTimeouts(key);
    // Factory çalıştırmak yerine stale veri döndürmeyi veya hata döndürmeyi düşün
}
```

### 8.3 Düşük Öncelikli Sorunlar

#### Sorun 5: Background Refresh Error Handling

**Konum:** `CacheService.ExecuteBackgroundRefreshAsync()`

**Problem:** Başarısız refresh'ler loglanır ama retry mekanizması yok

**Öneri:**
- Exponential backoff ile retry implement et
- Ardışık hataları takip et ve threshold'dan sonra SWR'ı disable et

```csharp
private async Task ExecuteBackgroundRefreshAsync<T>(string key, Factory factory)
{
    var retryCount = 0;
    while (retryCount < 3)
    {
        try
        {
            var value = await factory();
            await SetAsync(key, value);
            return;
        }
        catch (Exception ex)
        {
            retryCount++;
            if (retryCount >= 3)
            {
                _logger.LogError(ex, "{CacheKey} için background refresh 3 deneme sonra başarısız", key);
                return;
            }
            await Task.Delay(TimeSpan.FromSeconds(Math.Pow(2, retryCount)));
        }
    }
}
```

### 8.4 Geliştirme Önerileri

#### Geliştirme 1: Cache Warming Stratejisi

**Amaç:** Uygulama başlangıcında cache'i pre-populate et

```csharp
public class CacheWarmupService : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var warmupQueries = new List<ICacheableQuery>
        {
            new GetPostsListQueryRequest { PageNumber = 1 },
            new GetAllCategoryQueryRequest(),
            new GetAllTagQueryRequest()
        };

        foreach (var query in warmupQueries)
        {
            await _mediator.Send(query, stoppingToken);
        }
    }
}
```

#### Geliştirme 2: Dağıtık Cache Locking

**Amaç:** Birden fazla instance arasında stampede önle

```csharp
public class RedisDistributedLock
{
    public async Task<IDisposable> AcquireLockAsync(string key, TimeSpan timeout)
    {
        var lockKey = $"lock:{key}";
        var lockValue = Guid.NewGuid().ToString();
        var db = _connection.GetDatabase();

        var acquired = await db.StringSetAsync(lockKey, lockValue, timeout, When.NotExists);
        if (!acquired) throw new TimeoutException("Kilit alınamadı");

        return new DisposableLock(() => db.KeyDeleteAsync(lockKey));
    }
}
```

#### Geliştirme 3: Cache Health Checks

**Amaç:** Production'da cache sağlığını izle

```csharp
public class CacheHealthCheck : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken ct = default)
    {
        try
        {
            var testKey = "health-check";
            var testValue = DateTime.UtcNow;

            await _cache.SetAsync(testKey, testValue, TimeSpan.FromSeconds(10));
            var retrieved = await _cache.GetAsync<DateTime>(testKey);
            await _cache.RemoveAsync(testKey);

            if (retrieved == testValue)
                return HealthCheckResult.Healthy("Cache operasyonel");

            return HealthCheckResult.Degraded("Cache beklenmeyen değer döndürdü");
        }
        catch (Exception ex)
        {
            return HealthCheckResult.Unhealthy("Cache hatası", ex);
        }
    }
}
```

---

## 9. Performans Karakteristikleri

### 9.1 Beklenen Gecikme

| Operasyon | Beklenen Gecikme | Notlar |
|-----------|-----------------|-------|
| **L1 Hit** | < 1ms | In-memory lookup |
| **L2 Hit** | 5-15ms | Redis network round-trip |
| **L1 Miss + L2 Hit** | 10-20ms | L1 miss + L2 hit + promotion |
| **Cache Miss** | Değişken | DB sorgu süresi (genelde 50-500ms) |
| **SWR Stale** | < 1ms | L1'den anında döndür |
| **SWR Refresh** | Background | Response süresi üzerinde etkisi yok |

### 9.2 Hit Rate Hedefleri

| Katman | Hedef Hit Rate | Altında ise Aksiyon |
|-------|----------------|---------------------|
| **L1** | > %80 | L1 TTL'sini artır veya cache key space'ini azalt |
| **L2** | > %90 | Cache churn'ü incele veya L2 TTL'sini artır |
| **Overall** | > %95 | Caching stratejisini ve anahtar tasarımını gözden geçir |

### 9.3 Ölçeklenebilirlik Hususları

| Senaryo | Etki | Mitigasyon |
|----------|------|------------|
| **Birden Fazla Instance** | L1 cache her instance'da ayrı | L2 shared cache sağlar |
| **Yüksek Trafik** | Stampede riski | Semaphore locks + SWR |
| **Büyük Veriseti** | Redis bellek baskısı | Uygun TTL ayarla, sıcak veri için L1 kullan |
| **Network Gecikmesi** | L2 yavaşlaması | L1 L2 çağrılarını azaltır |
| **Redis Arızası** | Performans degradasyonu | In-memory cache fallback |

---

## 10. Best Practices ve İlkeler

### 10.1 Ne Zaman Caching Kullanılmalı

✅ **Caching Kullanım Alanları:**
- Okuma ağırlıklı sorgular (blog postları, kategoriler, etiketler)
- Pahalı hesaplamalar (arama sonuçları, aggregations)
- Sayfalı listeler
- Nadir değişen veriler

❌ **Caching Kullanılmamalı:**
- Real-time veriler (user session'ları, canlı sayaçlar)
- Sık değişen veriler (post görüntülenmeleri, yorum sayıları)
- Kullanıcıya özel veriler (sadece kullanıcı başına cache hariç)
- Yazma işlemleri (cache kullanmamalı, invalid etmeli)

### 10.2 Cache Anahtarı Tasarım İlkeleri

**Yapılmalı:**
- Hiyerarşik, açıklayıcı anahtarlar kullan
- Tanımlayıcıları ekle (ID, slug, sayfa numarası)
- İlgili anahtarları ortak prefix ile grupla
- Tutarlılık için cache anahtarı sabitleri kullan

**Yapılmamalı:**
- Timestamp'ler veya geçici veriler içeren anahtarlar kullanma
- Aşırı karmaşık anahtar yapıları oluştur
- Rastgele veya UUID tabanlı anahtarlar kullan (gerekli olmadıkça)

### 10.3 TTL Seçim İlkeleri

| Veri Tipi | Önerilen TTL | Gerekçe |
|-----------|--------------|---------|
| **Blog Postları** | 5-15 dk | Nadir değişir, sık okunur |
| **Kategoriler** | 30-60 dk | Nadir değişir |
| **Etiketler** | 30-60 dk | Nadir değişir |
| **Arama Sonuçları** | 2-5 dk | Orta değişim sıklığı |
| **Kullanıcı Verileri** | 1-5 dk | Kullanıcıya özel, sık güncelleme |

### 10.4 Test İlkeleri

**Unit Testler:**
- Cache hit/miss senaryolarını test et
- Yazma işlemlerinde cache invalidasyonunu test et
- Soft/hard expiration ile SWR davranışını test et
- Eşzamanlı isteklerle stampede korumasını test et

**Integration Testler:**
- Redis bağlantı hatalarını test et
- SignalR bildirim teslimatını test et
**Cross-instance cache invalidasyonunu test et**
- **Başlangıçta cache warming'i test et**

**Performans Testleri:**
- Yük altında hit rate'lerini ölç
- Milyonlarca cache anahtarı ile test et
- Eşzamanlı yazma invalidasyonunu test et
- Background refresh etkisini test et

---

## 11. Ek: Dosya Referansı

### 11.1 Temel Cache Dosyaları

| Dosya Yolu | Amaç |
|------------|------|
| `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Abstractions/CacheResult.cs` | SWR sonuç wrapper'ı |
| `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Abstractions/IBasicCacheService.cs` | Temel cache interface'i |
| `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Abstractions/IHybridCacheService.cs` | Hibrit cache interface'i |
| `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Services/HybridCacheServiceBase.cs` | Hibrit cache base implementasyonu |
| `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Redis/BasicRedisCacheService.cs` | Basit Redis implementasyonu |
| `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Extensions/CacheKeyExtensions.cs` | Anahtar utility metodları |
| `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Metrics/CacheMetrics.cs` | Metrik toplama |
| `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Options/RedisSettings.cs` | Redis konfigürasyonu |
| `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/DependencyInjection.cs` | Servis kaydı |

### 11.2 Application Cache Dosyaları

| Dosya Yolu | Amaç |
|------------|------|
| `src/BlogApp.Server/BlogApp.Server.Infrastructure/Services/CacheService.cs` | Domain cache servisi |
| `src/BlogApp.Server/BlogApp.Server.Application/Common/Behaviors/CachingBehavior.cs` | MediatR caching pipeline'ı |
| `src/BlogApp.Server/BlogApp.Server.Application/Common/Interfaces/Services/ICacheService.cs` | Domain cache interface'i |
| `src/BlogApp.Server/BlogApp.Server.Application/Common/Interfaces/Services/ICacheInvalidationNotifier.cs` | Bildirim interface'i |
| `src/BlogApp.Server/BlogApp.Server.Api/Services/CacheInvalidationNotifier.cs` | SignalR notifier'ı |
| `src/BlogApp.Server/BlogApp.Server.Api/Hubs/CacheInvalidationHub.cs` | SignalR hub'ı |
| `src/BlogApp.Server/BlogApp.Server.Infrastructure/DependencyInjection.cs` | Infrastructure DI kaydı |
| `src/BlogApp.Server/BlogApp.Server.Application/DependencyInjection.cs` | Application DI kaydı |

### 11.3 Cache Anahtarı Sabitleri

| Dosya Yolu | Amaç |
|------------|------|
| `src/BlogApp.Server/BlogApp.Server.Application/Features/PostFeature/Constants/PostCacheKeys.cs` | Post cache anahtarları |
| `src/BlogApp.Server/BlogApp.Server.Application/Features/CategoryFeature/Constants/CategoryCacheKeys.cs` | Category cache anahtarları |
| `src/BlogApp.Server/BlogApp.Server.Application/Features/TagFeature/Constants/TagCacheKeys.cs` | Tag cache anahtarları |

### 11.4 Frontend Cache Dosyaları

| Dosya Yolu | Amaç |
|------------|------|
| `src/blogapp-web/src/hooks/use-cache-sync.ts` | Cache sync hook'u |
| `src/blogapp-web/src/components/cache-sync-provider.tsx` | Cache sync context provider'ı |
| `src/blogapp-web/src/hooks/use-cache-synced-data.ts` | SWR veri hook'u |

---

## 12. Özet

BlogApp caching mimarisi **iyi tasarlanmış ve production-ready** durumda ve aşağıdaki güçlülüklere sahip:

### Güçlü Yönler
- ✅ Modern hibrit L1/L2 caching stratejisi
- ✅ Optimum performans için Stale-While-Revalidate deseni
- ✅ OpenTelemetry ile kapsamlı gözlemlenebilirlik
- ✅ SignalR ile gerçek zamanlı frontend senkronizasyonu
- ✅ Redis kullanılamazken graceful degradation
- ✅ Cache stampede koruması
- ✅ Versiyon tabanlı grup invalidasyonu

### İyileştirme Alanları
- ⚠️ Anahtar expiration tracking'de bellek sızıntısı riski
- ⚠️ Bulk invalidasyon için Redis SCAN performansı
- ⚠️ Sessiz SignalR bildirim hataları
- ⚠️ Lock timeout handling

### Genel Değerlendirme
Caching sistemi yüksek performanslı bir blog uygulaması için **sağlam bir temel** sunmaktadır. Tespit edilen sorunlar **çözülebilir** ve production deploy'unu engellememeli, ancak uzun vadeli稳定性 için yakın gelecekte ele alınmalıdır.

---

**Raporu Hazırlayan:** Claude Code (Sonnet 4.5)
**Analiz Tarihi:** 2026-02-01
**Sonraki İnceleme Tarihi:** 2026-03-01
