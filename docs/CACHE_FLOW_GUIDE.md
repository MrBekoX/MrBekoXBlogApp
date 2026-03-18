# Cache Mimarisi - Detaylı Akış Rehberi

**Tarih:** 2026-02-01
**Amaç:** Her istek tipi için cache mimarisinin adım adım çalışma prensibi

---

## 📚 İçindekiler

1. [GET İsteği - Standart Cache](#1-get-isteği---standart-cache)
2. [GET İsteği - SWR Fresh Data](#2-get-isteği---swr-fresh-data)
3. [GET İsteği - SWR Stale Data](#3-get-isteği---swr-stale-data)
4. [POST İsteği - Yeni Kayıt](#4-post-isteği---yeni-kayıt)
5. [PUT/PATCH İsteği - Güncelleme](#5putpatch-isteği---güncelleme)
6. [DELETE İsteği - Silme](#6-delete-isteği---silme)
7. [Özet Tablo](#özet-tablo)
8. [Kritik Noktalar](#kritik-noktalar)

---

## 1. GET İsteği - Standart Cache

Kullanıcı makale listesini ilk kez çektiğinde ne olur?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     KULLANICI GET İSTEĞİ GÖNDERİR                           │
│              "GET /api/v1/posts?page=1&pageSize=10"                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. MEDIATR PIPELINE BAŞLAR                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Pipeline Sırası:                                                  │   │
│  │  1. LoggingBehavior    → Request'i logla                         │   │
│  │  2. CachingBehavior   → Cache kontrol et                         │   │
│  │  3. ValidationBehavior → Validate et                              │   │
│  │  4. Handler           → İşle                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  2. CachingBehavior.Handle() - Cache Kontrolü                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  public class GetPostsListQueryRequest : ICacheableQuery            │   │
│  │  {                                                                  │   │
│  │      public int PageNumber { get; init } = 1;                       │   │
│  │      public int PageSize { get; init } = 10;                       │   │
│  │                                                                      │   │
│  │      // Cache anahtarı: Parametrelerden oluşur                      │   │
│  │      public string CacheKey =>                                      │   │
│  │          $"posts-list-{PageNumber}-{PageSize}-{SearchTerm}-...";   │   │
│  │      // Sonuç: "posts-list-1-10------false-CreatedAt-true"         │   │
│  │                                                                      │   │
│  │      // Cache grubu: Versiyon tabanlı invalidation için             │   │
│  │      public string? CacheGroup => "posts_list";                     │   │
│  │                                                                      │   │
│  │      // Cache süresi: 10 dakika (SWR için hard expiration)          │   │
│  │      public TimeSpan? CacheDuration => TimeSpan.FromMinutes(10);   │   │
│  │                                                                      │   │
│  │      // SWR pattern: Stale data'yı anında döndür, arka planda yenile│   │
│  │      public bool UseStaleWhileRevalidate => true;                   │   │
│  │                                                                      │   │
│  │      // SWR oranı: Soft expiration = 50% of hard                    │   │
│  │      public double SwrSoftRatio => 0.5;                             │   │
│  │      // Soft: 5dk, Hard: 10dk                                      │   │
│  │  }                                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  // Grup versiyonunu Redis'tan al                                          │
│  version = await _cacheService.GetGroupVersionAsync("posts_list");        │
│  // İlk request: version = 1                                               │
│                                                                             │
│  // Versiyonlu cache anahtarını oluştur                                    │
│  cacheKey = "posts_list:v1:posts-list-1-10------false-CreatedAt-true";   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  3. cacheService.GetOrSetWithSwrAsync() - L1 KONTROL                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // HybridCacheServiceBase.GetAsync<T>(key)                        │   │
│  │                                                                      │   │
│  │  // L1 cache kontrol (IMemoryCache - RAM'da)                        │   │
│  │  if (L1Cache.TryGetValue(key, out T? l1Value))                     │   │
│  │  {                                                                 │   │
│  │      // ✅ L1 HIT - Ultra hızlı! (< 1ms)                           │   │
│  │      Metrics.RecordL1Hit(keyPrefix);                               │   │
│  │      Logger.LogDebug("L1 cache hit for key {Key}", key);           │   │
│  │      return l1Value;                                               │   │
│  │  }                                                                 │   │
│  │                                                                      │   │
│  │  Metrics.RecordL1Miss(keyPrefix);                                  │   │
│  │  return default;  // Cache miss                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Sonuç: L1'de bulunamadı ❌ (ilk request)                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  4. L2 CACHE KONTROL (Redis)                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // Redis/Distributed cache kontrol                                 │   │
│  │  var l2Data = await L2Cache.GetStringAsync(key, cancellationToken);│   │
│  │                                                                      │   │
│  │  if (string.IsNullOrEmpty(l2Data))                                 │   │
│  │  {                                                                 │   │
│  │      // ❌ L2 MISS - Cache'te yok                                   │   │
│  │      Metrics.RecordL2Miss(keyPrefix);                              │   │
│  │      _keyExpirations.TryRemove(key, out _);                        │   │
│  │      return default;                                               │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Sonuç: L2'de bulunamadı ❌ (ilk request)                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  5. CACHE STAMPEDE KORUMASI - KİLİT ALMA                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // Problem: 100 aynı anda istek gelirse?                          │   │
│  │  // Çözüm: Her anahtar için ayrı kilit                              │   │
│  │                                                                      │   │
│  │  var keyLock = _locks.GetOrAdd(key, _ => new SemaphoreSlim(1, 1));│   │
│  │  // ConcurrentDictionary'de varsa al, yoksa oluştur                │   │
│  │                                                                      │   │
│  │  // Kilidi al (timeout: 30 saniye)                                  │   │
│  │  lockAcquired = await keyLock.WaitAsync(LockTimeout, ct);          │   │
│  │                                                                      │   │
│  │  if (!lockAcquired)                                                 │   │
│  │  {                                                                 │   │
│  │      // Timeout: Kilit alınamadı                                   │   │
│  │      Logger.LogWarning("Lock timeout for {Key}");                  │   │
│  │      Metrics.RecordLockTimeout(keyPrefix);                         │   │
│  │      // Fallback: Kilitsiz çalıştır (askıda kalma)                 │   │
│  │      var fallbackValue = await factory();                          │   │
│  │      await SetAsync(key, fallbackValue, expiration, ct);           │   │
│  │      return fallbackValue;                                         │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Sonuç: ✅ Kilit alındı (30sn içinde)                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  6. DOUBLE-CHECK PATTERN (Stampede Önleme)                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // Kilidi alan ilk request factory'ı çalıştırmadan önce            │   │
│  │  // TEKRAR cache kontrol et (başka request çalıştırmış olabilir)   │   │
│  │                                                                      │   │
│  │  // Double-check L1 after acquiring lock                            │   │
│  │  if (L1Cache.TryGetValue(key, out l1Value))                         │   │
│  │  {                                                                 │   │
│  │      // ✅ L1 HIT (başka request populate etmiş)                    │   │
│  │      Logger.LogDebug("L1 cache hit after lock (stampede prevented)");│   │
│  │      Metrics.RecordStampedePrevented(keyPrefix);                    │   │
│  │      Metrics.RecordL1Hit(keyPrefix);                                │   │
│  │      return l1Value!;                                               │   │
│  │  }                                                                 │   │
│  │                                                                      │   │
│  │  // Double-check L2 after acquiring lock                            │   │
│  │  cached = await GetFromL2Async<T>(key, keyPrefix, ct);             │   │
│  │  if (cached is not null)                                            │   │
│  │  {                                                                 │   │
│  │      // ✅ L2 HIT (başka request populate etmiş)                    │   │
│  │      Logger.LogDebug("L2 cache hit after lock (stampede prevented)");│   │
│  │      Metrics.RecordStampedePrevented(keyPrefix);                    │   │
│  │      return cached;                                                 │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Sonuç: Hala cache miss ✅ Biz factory'ı çalıştıracağız                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  7. FACTORY ÇALIŞTIRMA (Handler Execution)                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // CachingBehavior'dan gelen next() callback'ı                    │   │
│  │  // Bu callback tüm pipeline'ı (validation + handler) çalıştırır   │   │
│  │                                                                      │   │
│  │  var response = await next();                                       │   │
│  │                                                                      │   │
│  │  // GetPostsListQueryHandler.Handle() çalışır:                     │   │
│  │  public async Task<GetPostsListQueryResponse> Handle(               │   │
│  │      GetPostsListQueryRequest request,                              │   │
│  │      CancellationToken ct)                                          │   │
│  │  {                                                                 │   │
│  │      // Repository'den veri çek                                     │   │
│  │      var posts = await _postReadRepository.GetPagedAsync(          │   │
│  │          request.PageNumber,                                        │   │
│  │          request.PageSize,                                          │   │
│  │          request.SearchTerm,                                        │   │
│  │          request.CategoryId,                                        │   │
│  │          request.TagId,                                             │   │
│  │          request.SortBy,                                            │   │
│  │          request.SortDescending,                                   │   │
│  │          ct);                                                       │   │
│  │      // 🐢 SLOW: DB sorgusu (50-500ms)                              │   │
│  │      // SQL: SELECT * FROM Posts WHERE ... ORDER BY ... OFFSET ...  │   │
│  │                                                                      │   │
│  │      return new GetPostsListQueryResponse                          │   │
│  │      {                                                             │   │
│  │          Posts = posts.ToList(),                                   │   │
│  │          TotalCount = posts.TotalCount                             │   │
│  │      };                                                           │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  8. CACHE'E YAZMA (Write-Through Strategy)                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // SWR için metadata ile cache'e yaz                               │   │
│  │  await SetWithSoftExpirationAsync(key, response,                    │   │
│  │      softExpiration: 5 dakika,                                      │   │
│  │      hardExpiration: 10 dakika);                                    │   │
│  │                                                                      │   │
│  │  // SwrCacheEntry oluştur:                                          │   │
│  │  var entry = new SwrCacheEntry<Response>(                           │   │
│  │      Value: response,                                               │   │
│  │      SoftExpiration: DateTime.UtcNow + 5 dakika                    │   │
│  │  );                                                                │   │
│  │                                                                      │   │
│  │  // L1'e yaz (IMemoryCache)                                         │   │
│  │  var l1Expiration = CalculateL1Expiration(10dk);                    │   │
│  │  // L1 TTL = min(10sn, 10dk / 10) = 10sn                            │   │
│  │                                                                      │   │
│  │  var l1Options = new MemoryCacheEntryOptions                         │   │
│  │  {                                                                 │   │
│  │      AbsoluteExpirationRelativeToNow = TimeSpan.FromSeconds(10)    │   │
│  │  };                                                                │   │
│  │  L1Cache.Set(key, entry, l1Options);                                │   │
│  │  Interlocked.Increment(ref _l1KeyCount);                           │   │
│  │                                                                      │   │
│  │  // L2'ye yaz (Redis)                                               │   │
│  │  var l2Options = new DistributedCacheEntryOptions                   │   │
│  │  {                                                                 │   │
│  │      AbsoluteExpirationRelativeToNow = TimeSpan.FromMinutes(10)    │   │
│  │  };                                                                │   │
│  │  var serialized = JsonSerializer.Serialize(entry);                 │   │
│  │  await L2Cache.SetStringAsync(key, serialized, l2Options, ct);     │   │
│  │                                                                      │   │
│  │  // Key'i metadata tracking için kaydet                             │   │
│  │  TrackKey(key, 10dk);                                              │   │
│  │  Metrics.RecordWrite(keyPrefix);                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Cache'e yazıldı: ✅                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  L1 (RAM):                                                           │   │
│  │  Key: "posts_list:v1:posts-list-1-10------false-CreatedAt-true"    │   │
│  │  Value: { Posts: [...], TotalCount: 100, SoftExpiration: ... }      │   │
│  │  TTL: 10 saniye                                                     │   │
│  │                                                                      │   │
│  │  L2 (Redis):                                                         │   │
│  │  Key: "BlogApp:posts_list:v1:posts-list-1-10------false-CreatedAt-true"│   │
│  │  Value: { Posts: [...], TotalCount: 100, SoftExpiration: ... }      │   │
│  │  TTL: 10 dakika                                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  9. KİLİTI SERBEST BIRAKMA                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  finally {                                                         │   │
│  │      if (lockAcquired)                                            │   │
│  │          keyLock.Release();  // Semaphore release                  │   │
│  │                                                                      │   │
│  │      // Gereksiz lock'ları temizle (1000'den fazlaysa)             │   │
│  │      CleanupLockIfUnused(key, keyLock);                            │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Kilit serbest bırakıldı 🔓                                                 │
│  Diğer bekleyen request'ler artık cache'den okuyabilecek 🎯                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  10. RESPONSE DÖNDÜRME                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  return response;  // JSON response                                 │   │
│  │                                                                      │   │
│  │  HTTP 200 OK                                                        │   │
│  │  Content-Type: application/json                                    │   │
│  │  {                                                                 │   │
│  │    "posts": [                                                       │   │
│  │      {                                                             │   │
│  │        "id": "123",                                                │   │
│  │        "title": "Hello World",                                     │   │
│  │        "slug": "hello-world",                                      │   │
│  │        "content": "...",                                           │   │
│  │        "createdAt": "2026-02-01T10:00:00Z"                         │   │
│  │      },                                                            │   │
│  │      ...                                                           │   │
│  │    ],                                                              │   │
│  │    "totalCount": 100,                                              │   │
│  │    "pageNumber": 1,                                               │   │
│  │    "pageSize": 10                                                 │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   ✅ KULLANICIYA VERİ DÖNDÜ (550ms sonra)                  │
│                                                                             │
│  Toplam Süre: ~550ms                                                        │
│  - L1 kontrol: <1ms                                                         │
│  - L2 kontrol: 10ms                                                         │
│  - Kilit alma: <1ms                                                         │
│  - Double-check: <1ms                                                       │
│  - DB sorgusu: ~500ms (🐢 şişe瓶颈)                                        │
│  - Cache yazma: 30ms                                                        │
│  - Kilit release: <1ms                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. GET İsteği - SWR Fresh Data

**Aynı kullanıcı 3 dakika sonra tekrar istekte bulunduğunda:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              KULLANICI TEKRAR İSTEK GÖNDERİR (3 dk sonra)                    │
│              "GET /api/v1/posts?page=1&pageSize=10"                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. MEDIATR PIPELINE + CachingBehavior                                      │
│  Cache key: "posts_list:v1:posts-list-1-10------false-CreatedAt-true"     │
│  Version: 1 (değişmedi)                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  2. L1 CACHE KONTROL                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // L1 kontrol (IMemoryCache)                                     │   │
│  │  if (L1Cache.TryGetValue(key, out SwrCacheEntry? l1Entry))         │   │
│  │  {                                                                 │   │
│  │      // ❌ L1 MISS                                                │   │
│  │      // Sebep: L1 TTL = 10 saniye                                  │   │
│  │      // 3 dakika geçmiş, L1 cache expired                          │   │
│  │  }                                                                 │   │
│  │                                                                      │   │
│  │  Metrics.RecordL1Miss(keyPrefix);                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Sonuç: L1 miss ❌ (10 saniye TTL çoktan geçti)                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  3. L2 CACHE KONTROL (Redis - SWR Metadata ile)                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  var l2Data = await L2Cache.GetStringAsync(key, ct);                │   │
│  │                                                                      │   │
│  │  // Redis'ten JSON deserialize et                                   │   │
│  │  var entry = JsonSerializer.Deserialize<SwrCacheEntry<Response>>    │   │
│  │      (l2Data);                                                      │   │
│  │                                                                      │   │
│  │  // SWR Cache Entry:                                                 │   │
│  │  SwrCacheEntry {                                                    │   │
│  │      Value: GetPostsListQueryResponse {                             │   │
│  │          Posts: [ ... ],                                            │   │
│  │          TotalCount: 100                                            │   │
│  │      },                                                             │   │
│  │      SoftExpiration: 2026-02-01T10:05:00Z  (5 dk sonra)            │   │
│  │  }                                                                  │   │
│  │                                                                      │   │
│  │  // Şu anki zaman: 2026-02-01T10:03:00Z (3 dk sonra)                │   │
│  │  var isStale = (DateTime.UtcNow > entry.SoftExpiration);            │   │
│  │  // isStale = false (henüz fresh) ✅                                │   │
│  │                                                                      │   │
│  │  // FRESH DATA - Metrics kaydet                                     │   │
│  │  Metrics.RecordL2Hit(keyPrefix);                                    │   │
│  │  Metrics.RecordSwrFreshHit(keyPrefix);                              │   │
│  │                                                                      │   │
│  │  // L1'e promote et (tekrar sonraki request için)                   │   │
│  │  PromoteToL1(key, entry);                                           │   │
│  │  // L1'e 10 saniye TTL ile koy                                     │   │
│  │  Metrics.RecordL1Promotion(keyPrefix);                              │   │
│  │                                                                      │   │
│  │  return CacheResult(entry.Value, isStale: false, isHit: true);     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Sonuç: ✅ L2 HIT - Fresh data!                                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  4. RESPONSE DÖNDÜRME (FRESH DATA)                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  if (result.IsHit && !result.IsStale)                              │   │
│  │  {                                                                 │   │
│  │      // ✅ FRESH DATA - Direkt döndür                              │   │
│  │      Logger.LogDebug("SWR: Fresh hit for {Key}", key);             │   │
│  │      return result.Value!;                                         │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Toplam Süre: ~15ms                                                         │
│  - L1 kontrol: <1ms (miss)                                                 │
│  - L2 kontrol + deserialize: 10ms                                          │
│  - L1 promotion: 4ms                                                       │
│  - ❌ DB sorgusu YOK! 🚀                                                    │
│                                                                             │
│  Performans kazancı: 550ms → 15ms (~37x faster!)                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ✅ KULLANICIYA FRESH VERİ DÖNDÜ (15ms)                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. GET İsteği - SWR Stale Data

**Kullanıcı 6 dakika sonra tekrar istekte bulunduğunda:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              KULLANICI 6 DAKİKA SONRA İSTEK GÖNDERİR                        │
│              "GET /api/v1/posts?page=1&pageSize=10"                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. MEDIATR PIPELINE + CachingBehavior                                      │
│  Cache key: "posts_list:v1:posts-list-1-10------false-CreatedAt-true"     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  2. L1 CACHE KONTROL (Expired ❌)                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  if (L1Cache.TryGetValue(key, out l1Entry))                         │   │
│  │  {                                                                 │   │
│  │      // ❌ L1 MISS                                                │   │
│  │      // Sebep: L1 TTL = 10 saniye                                  │   │
│  │      // 6 dakika geçmiş, kesinlikle expired                         │   │
│  │  }                                                                 │   │
│  │                                                                      │   │
│  │  Metrics.RecordL1Miss(keyPrefix);                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Sonuç: L1 miss ❌                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  3. L2 CACHE KONTROL - STALE DATA TESPİTİ!                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  var l2Data = await L2Cache.GetStringAsync(key, ct);                │   │
│  │  var entry = JsonSerializer.Deserialize<SwrCacheEntry<Response>>    │   │
│  │      (l2Data);                                                      │   │
│  │                                                                      │   │
│  │  // SWR Metadata:                                                   │   │
│  │  entry.SoftExpiration = 2026-02-01T10:05:00Z  (5 dk sonra)          │   │
│  │                                                                      │   │
│  │  // Şu anki zaman: 2026-02-01T10:06:00Z (6 dk sonra)                │   │
│  │  var isStale = (DateTime.UtcNow > entry.SoftExpiration);            │   │
│  │  // isStale = true ⚠️ (soft expiration geçmiş)                     │   │
│  │                                                                      │   │
│  │  // STALE DATA - Metrics kaydet                                    │   │
│  │  Metrics.RecordL2Hit(keyPrefix);                                    │   │
│  │  Metrics.RecordSwrStaleHit(keyPrefix);                              │   │
│  │                                                                      │   │
│  │  // L1'e promote et (stale olsa bile)                               │   │
│  │  PromoteToL1(key, entry);                                           │   │
│  │  Metrics.RecordL1Promotion(keyPrefix);                              │   │
│  │                                                                      │   │
│  │  return CacheResult(entry.Value, isStale: true, isHit: true);      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Sonuç: ✅ L2 HIT - Ama STALE ⚠️ (5 dk sonra expire olmuş)                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  4. SWR: STALE VERİYİ HEMEN DÖNDÜR, ARKADA REFRESH TETİKLE!                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // HybridCacheServiceBase.GetOrSetWithSwrAsync()                  │   │
│  │                                                                      │   │
│  │  var result = await GetWithMetadataAsync<Response>(key, ct);       │   │
│  │  // result.IsHit = true, result.IsStale = true                     │   │
│  │                                                                      │   │
│  │  if (result.IsStale)                                               │   │
│  │  {                                                                 │   │
│  │      // 🚀 STALE VERİYİ ANINDA DÖNDÜR (Kullanıcı beklemez!)       │   │
│  │      Logger.LogDebug("SWR: Returning stale value for {Key}, " +    │   │
│  │          "triggering background refresh", key);                    │   │
│  │      Metrics.RecordSwrBackgroundRefresh(keyPrefix);                │   │
│  │                                                                      │   │
│  │      // 🔄 ARKA PLANDA REFRESH TETİKLE                             │   │
│  │      _ = OnSwrBackgroundRefreshNeededAsync(key, factory,           │   │
│  │          softExpiration, hardExpiration, keyPrefix);               │   │
│  │                                                                      │   │
│  │      // ⚠️ DİKKAT: Task.Run ile fire-and-forget                   │   │
│  │      // Kullanıcıyı beklemez, hemen stale data döndürür             │   │
│  │                                                                      │   │
│  │      return result.Value!;  // STALE VERİ DÖNDÜR                   │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Kullanıcıya stale veri hemen döndürüldü ✅                                 │
│  Background refresh başladı ⏳                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
         ┌──────────────────────────┐   ┌──────────────────────────┐
         │     ANA THREAD           │   │   BACKGROUND THREAD      │
         │  (Kullanıcıya Response)  │   │   (Cache Refresh)        │
         └──────────────────────────┘   └──────────────────────────┘
                    │                               │
                    ▼                               ▼
┌───────────────────────────────┐   ┌───────────────────────────────┐
│  ✅ STALE VERİ DÖNDÜR          │   │  1. Task.Run(async)         │
│  Süre: < 1ms 🚀                │   │  2. Yeni DI Scope oluştur  │
│                               │   │     using var scope =        │
│  HTTP 200 OK                  │   │       _serviceScopeFactory.  │
│  {                            │   │       CreateScope();         │
│    "posts": [...],             │   │                              │
│    "totalCount": 100           │   │  3. IMediator al            │
│  }                            │   │     var mediator =           │
│                               │   │       scope.ServiceProvider. │
│  Kullanıcı memnun 😊           │   │       GetRequiredService<    │
│  (Veri biraz eski olabilir)    │   │       IMediator>();          │
│  ama response süper hızlı!     │   │                              │
└───────────────────────────────┘   │  4. Handler'ı tekrar çalıştır │
                                   │     var freshValue =          │
                                   │       await mediator.Send(    │
                                   │           request);           │
                                   │     // 🐢 DB Query (50-500ms)│
                                   │                              │
                                   │  5. Cache'i güncelle          │
                                   │     await SetWithSoft         │
                                   │       ExpirationAsync(        │
                                   │         key, freshValue,      │
                                   │         softExp, hardExp);    │
                                   │                              │
                                   │  6. Log success               │
                                   │     Logger.LogDebug(         │
                                   │       "Background refresh " + │
                                   │       "completed");           │
                                   └───────────────────────────────┘
                                                  │
                                                  ▼
                                   ┌─────────────────────────────────┐
                                   │  ✅ BACKGROUND REFRESH TAMAM     │
                                   │  Cache güncellendi:              │
                                   │  - L1: Fresh data (10sn TTL)    │
                                   │  - L2: Fresh data (10dk TTL)    │
                                   │                                  │
                                   │  Sonraki request'te fresh data   │
                                   │  dönecek! ✅                    │
                                   └─────────────────────────────────┘
```

**Sonraki request'te (1 dakika sonra):**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│              KULLANICI TEKRAR İSTEK GÖNDERİR (1 dk sonra)                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  L1 kontrol → ✅ HIT (fresh data, background refresh tamamlanmış)         │
│                                                                             │
│  Cache entry:                                                              │
│  - Value: Fresh data (background refresh ile güncellendi)                 │
│  - SoftExpiration: 10:11:00Z (5 dk sonra, yenilendi)                       │
│  - Şu an: 10:07:00Z (fresh) ✅                                             │
│                                                                             │
│  Response: < 1ms 🚀                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. POST İsteği - Yeni Kayıt

**Admin yeni bir makale oluşturduğunda:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              KULLANICI YENİ MAKALE OLUŞTURUR                                │
│              "POST /api/v1/posts" + {...postData}                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. MEDIATR PIPELINE - CachingBehavior YOK!                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  public class CreatePostCommandRequest                               │   │
│  │      : IRequest<CreatePostCommandResponse>                          │   │
│  │  {                                                                 │   │
│  │      public string Title { get; init; }                              │   │
│  │      public string Content { get; init; }                            │   │
│  │      // ...                                                          │   │
│  │      // ❌ ICacheableQuery DEĞİL - Cache'lenebilir query değil        │   │
│  │      // Bu bir COMMAND - Write işlemi                                │   │
│  │  }                                                                 │   │
│  │                                                                      │   │
│  │  Pipeline:                                                           │   │
│  │  1. LoggingBehavior    → Request'i logla                           │   │
│  │  2. ValidationBehavior → Validate et (title boş mu, etc.)           │   │
│  │  3. Handler            → İşle (CachingBehavior YOK)                  │   │
│  │                                                                      │   │
│  │  ⚠️ IMPORTANT: Write işlemleri NEVER cache'lenmez                   │   │
│  │  Sadece Query'ler (ICacheableQuery) cache'lenir                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  2. CreatePostCommandHandler.Handle()                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  public async Task<CreatePostCommandResponse> Handle(               │   │
│  │      CreatePostCommandRequest request,                              │   │
│  │      CancellationToken ct)                                          │   │
│  │  {                                                                 │   │
│  │      // 1. Yeni post entity oluştur                                │   │
│  │      var post = new BlogPost                                       │   │
│  │      {                                                             │   │
│  │          Id = Guid.NewGuid(),                                      │   │
│  │          Title = request.Title,                                    │   │
│  │          Content = request.Content,                                │   │
│  │          Slug = _slugService.Generate(request.Title),              │   │
│  │          Excerpt = _excerptService.Generate(request.Content),      │   │
│  │          Status = PostStatus.Draft,  // Varsayılan: Draft         │   │
│  │          AuthorId = _currentUserService.UserId,                    │   │
│  │          CategoryId = request.CategoryId,                          │   │
│  │          TagIds = request.TagIds,                                  │   │
│  │          CreatedAt = DateTime.UtcNow,                              │   │
│  │          UpdatedAt = DateTime.UtcNow,                              │   │
│  │          IsDeleted = false,                                        │   │
│  │          FeaturedImageUrl = request.FeaturedImageUrl               │   │
│  │      };                                                            │   │
│  │                                                                      │   │
│  │      // 2. Repository'ye ekle                                       │   │
│  │      await _postWriteRepository.AddAsync(post, ct);                │   │
│  │                                                                      │   │
│  │      // 3. Veritabanına kaydet                                      │   │
│  │      await _unitOfWork.SaveChangesAsync(ct);                      │   │
│  │      // 🐢 DB INSERT (50-100ms)                                     │   │
│  │      // SQL: INSERT INTO Posts (...) VALUES (...)                  │   │
│  │                                                                      │   │
│  │      // 4. Cache invalidation (ÖNEMLİ!)                            │   │
│  │      // ⚠️ MEVCUT KODDA BULUNMUYOR - Manual eklenmeli              │   │
│  │      // List cache'leri invalid olmalı (yeni post eklendi)         │   │
│  │      await _cacheService.RotateGroupVersionAsync(                  │   │
│  │          PostCacheKeys.ListGroup, ct);                             │   │
│  │      // posts_list: v1 → v2                                        │   │
│  │                                                                      │   │
│  │      return new CreatePostCommandResponse                           │   │
│  │      {                                                             │   │
│  │          PostId = post.Id,                                         │   │
│  │          Slug = post.Slug,                                         │   │
│  │          Success = true                                            │   │
│  │      };                                                            │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  3. CACHE INVALIDATION (RotateGroupVersionAsync)                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // HybridCacheServiceBase.RotateGroupVersionAsync()               │   │
│  │                                                                      │   │
│  │  var versionKey = "cache_version:posts_list";                      │   │
│  │                                                                      │   │
│  │  // Redis path (atomic increment)                                  │   │
│  │  if (Redis?.IsConnected == true)                                   │   │
│  │  {                                                                 │   │
│  │      var db = Redis.GetDatabase();                                  │   │
│  │      var newVersion = await db.StringIncrementAsync(versionKey);   │   │
│  │      // Atomic: v1 → v2                                            │   │
│  │      // Tüm instance'lar için geçerli                              │   │
│  │                                                                      │   │
│  │      Logger.LogDebug("Rotated cache version for {Group} to {Ver}",  │   │
│  │          "posts_list", newVersion);                                 │   │
│  │                                                                      │   │
│  │      // L1 cache'i bu grup için temizle                            │   │
│  │      ClearL1ByPrefix("posts_list:");                                │   │
│  │      // Tüm "posts_list:*" anahtarları L1'den silindi              │   │
│  │  }                                                                 │   │
│  │                                                                      │   │
│  │  // Hook: SignalR notification                                     │   │
│  │  await OnGroupInvalidatedAsync("posts_list", ct);                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Cache version güncellendi: v1 → v2 ✅                                     │
│  Eski cache anahtarları artık geçersiz:                                     │
│  - "posts_list:v1:..." → invalid 🚫                                         │
│  - "posts_list:v2:..." → geçerli ✅                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  4. OTOMATİK SIGNALR BİLDİRİMİ (CacheService Hook)                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // CacheService.OnGroupInvalidatedAsync()                         │   │
│  │  protected override async Task OnGroupInvalidatedAsync(             │   │
│  │      string groupName, CancellationToken ct)                        │   │
│  │  {                                                                 │   │
│  │      if (_notifier != null)                                        │   │
│  │      {                                                             │   │
│  │          // Otomatik SignalR broadcast! 🪄                         │   │
│  │          await _notifier.NotifyGroupInvalidatedAsync(              │   │
│  │              groupName, ct);                                        │   │
│  │      }                                                             │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  // CacheInvalidationNotifier.NotifyGroupInvalidatedAsync()                │
│  var evt = new CacheInvalidationEvent(                                     │
│      type: CacheInvalidationType.GroupRotated,                             │
│      target: "posts_list",                                                 │
│      timestamp: DateTimeOffset.UtcNow                                      │
│  );                                                                         │
│                                                                             │
│  await _hubContext.Clients.All.SendAsync("CacheInvalidated", evt);          │
│  // Tüm bağlı istemcilere broadcast                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  5. FRONTEND CACHE INVALIDATION (use-cache-sync.ts)                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // Tüm bağlı frontend istemcileri                                 │   │
│  │  connection.on('CacheInvalidated', (event) => {                     │   │
│  │      console.log('Cache invalidated:', event);                      │   │
│  │      // {                                                           │   │
│  │      //   type: 'GroupRotated',                                     │   │
│  │      //   target: 'posts_list',                                     │   │
│  │      //   timestamp: '2026-02-01T10:07:00Z'                         │   │
│  │      // }                                                           │   │
│  │                                                                      │   │
│  │      onInvalidateRef.current?.(event);  // Callback tetikle        │   │
│  │  });                                                                 │   │
│  │                                                                      │   │
│  │  // React Query invalidation                                        │   │
│  │  onInvalidate: (event) => {                                         │   │
│  │      queryClient.invalidateQueries(['posts_list']);                │   │
│  │      // Frontend cache'teki tüm "posts_list" sorguları invalid edildi│   │
│  │  }                                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Frontend cache temizlendi ✅                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  6. RESPONSE DÖNDÜRME                                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  HTTP 201 Created                                                  │   │
│  │  Location: /api/v1/posts/{newPostId}                               │   │
│  │  {                                                                 │   │
│  │    "postId": "new-guid-456",                                        │   │
│  │    "slug": "yeni-makale",                                           │   │
│  │    "success": true                                                 │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     ✅ KULLANICIYA RESPONSE DÖNDÜ                           │
│                                                                             │
│  Sonraki GET /api/v1/posts isteğinde:                                       │
│  - Frontend cache boş → Backend'a request gider                           │
│  - Backend'de cache version v2                                             │
│  - DB'den yeni post ile birlikte listelenir ✅                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. PUT/PATCH İsteği - Güncelleme

**Admin bir makaleyi güncellediğinde:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              KULLANICI MAKALEYİ GÜNELLER                                    │
│              "PUT /api/v1/posts/{id}" + {...updatedData}                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. MEDIATR PIPELINE - CachingBehavior YOK                                  │
│  UpdatePostCommandRequest: IRequest<> (ICacheableQuery değil)              │
│  → LoggingBehavior → ValidationBehavior → Handler                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  2. UpdatePostCommandHandler.Handle()                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  public async Task<UpdatePostCommandResponse> Handle(               │   │
│  │      UpdatePostCommandRequest request,                              │   │
│  │      CancellationToken ct)                                          │   │
│  │  {                                                                 │   │
│  │      // 1. Mevcut post'u getir                                      │   │
│  │      var post = await _postReadRepository.GetByIdAsync(             │   │
│  │          request.Id, ct);                                           │   │
│  │      if (post is null)                                              │   │
│  │          return Failure("Post not found");                           │   │
│  │                                                                      │   │
│  │      var oldSlug = post.Slug;  // Eski slug'u sakla                 │   │
│  │                                                                      │   │
│  │      // 2. Güncelle                                                 │   │
│  │      post.Title = request.Title;                                    │   │
│  │      post.Content = request.Content;                                │   │
│  │      post.Slug = request.Slug;  // Slug değişebilir! ⚠️            │   │
│  │      post.CategoryId = request.CategoryId;                          │   │
│  │      post.TagIds = request.TagIds;                                  │   │
│  │      post.Status = request.Status;                                  │   │
│  │      post.UpdatedAt = DateTime.UtcNow;                              │   │
│  │      post.UpdatedBy = _currentUserService.UserName;                 │   │
│  │                                                                      │   │
│  │      // 3. Veritabanına kaydet                                      │   │
│  │      await _postWriteRepository.UpdateAsync(post, ct);              │   │
│  │      await _unitOfWork.SaveChangesAsync(ct);                        │   │
│  │      // 🐢 DB UPDATE (50-100ms)                                     │   │
│  │      // SQL: UPDATE Posts SET Title = ..., Slug = ... WHERE Id = ...│   │
│  │                                                                      │   │
│  │      return new UpdatePostCommandResponse { Success = true };      │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  3. CACHE INVALIDATION (3 adımda)                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // Adım 1: Tekil post cache'lerini temizle (by ID)                 │   │
│  │  await _cacheService.RemoveAsync(                                  │   │
│  │      PostCacheKeys.ById(post.Id), ct);                             │   │
│  │  // "post:id:123" → L1'den silindi, L2'den silindi                  │   │
│  │  // → SignalR broadcast: KeyRemoved("post:id:123")                 │   │
│  │                                                                      │   │
│  │  // Adım 2: Eski slug için cache temizle (slug değiştiyse)          │   │
│  │  if (oldSlug != post.Slug)                                         │   │
│  │  {                                                                 │   │
│  │      await _cacheService.RemoveAsync(                              │   │
│  │          PostCacheKeys.BySlug(oldSlug), ct);                       │   │
│  │      // "post:slug:eski-slug" → silindi                            │   │
│  │  }                                                                 │   │
│  │                                                                      │   │
│  │  // Adım 3: List cache'lerini invalid et (versiyon rotasyonu)       │   │
│  │  await _cacheService.RotateGroupVersionAsync(                      │   │
│  │      PostCacheKeys.ListGroup, ct);                                 │   │
│  │  // posts_list: v1 → v2                                            │   │
│  │  // → L1'deki tüm "posts_list:*" temizlendi                        │   │
│  │  // → SignalR broadcast: GroupRotated("posts_list")                 │   │
│  │                                                                      │   │
│  │  // ❌ Adım 4: SignalR bildirimleri OTOMATİK!                      │   │
│  │  // RemoveAsync() ve RotateGroupVersionAsync() çağrıldığında       │   │
│  │  // CacheService hook'ları otomatik SignalR gönderir               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  4. OTOMATİK SIGNALR BİLDİRİMLERİ (CacheService Hooks)                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  // Hook 1: RemoveAsync çağrıldığında otomatik                    │   │
│  │  protected override async Task OnKeyRemovedAsync(key, ct)          │   │
│  │  {                                                                 │   │
│  │      if (_notifier != null)                                        │   │
│  │      {                                                             │   │
│  │          // Otomatik SignalR broadcast                             │   │
│  │          await _notifier.NotifyKeyRemovedAsync(key, ct);           │   │
│  │      }                                                             │   │
│  │  }                                                                 │   │
│  │                                                                      │   │
│  │  // Broadcast 1:                                                    │   │
│  │  await _hubContext.Clients.All.SendAsync("CacheInvalidated",       │   │
│  │      new CacheInvalidationEvent(                                   │   │
│  │          type: KeyRemoved,                                         │   │
│  │          target: "post:id:123",                                    │   │
│  │          timestamp:.UtcNow));                                      │   │
│  │                                                                      │   │
│  │  // Hook 2: RotateGroupVersionAsync çağrıldığında otomatik         │   │
│  │  protected override async Task OnGroupInvalidatedAsync(group, ct)  │   │
│  │  {                                                                 │   │
│  │      if (_notifier != null)                                        │   │
│  │      {                                                             │   │
│  │          // Otomatik SignalR broadcast                             │   │
│  │          await _notifier.NotifyGroupInvalidatedAsync(group, ct);   │   │
│  │      }                                                             │   │
│  │  }                                                                 │   │
│  │                                                                      │   │
│  │  // Broadcast 2:                                                    │   │
│  │  await _hubContext.Clients.All.SendAsync("CacheInvalidated",       │   │
│  │      new CacheInvalidationEvent(                                   │   │
│  │          type: GroupRotated,                                       │   │
│  │          target: "posts_list",                                     │   │
│  │          timestamp:.UtcNow));                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  İki bildirim tüm bağlı istemcilere gider:                                  │
│  1. { type: "KeyRemoved", target: "post:id:123" }                         │
│  2. { type: "GroupRotated", target: "posts_list" }                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  5. FRONTEND CACHE INVALIDATION (use-cache-sync.ts)                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  connection.on('CacheInvalidated', (event) => {                     │   │
│  │      console.log('Cache invalidated:', event);                      │   │
│  │                                                                      │   │
│  │      if (event.type === 'KeyRemoved')                               │   │
│  │      {                                                             │   │
│  │          // Tekil post cache'ni invalid et                          │   │
│  │          queryClient.invalidateQueries(['post:id:123']);           │   │
│  │          // "post:id:123" → Frontend cache'ten silindi              │   │
│  │      }                                                             │   │
│  │                                                                      │   │
│  │      if (event.type === 'GroupRotated')                             │   │
│  │      {                                                             │   │
│  │          // Tüm post listelerini invalid et                         │   │
│  │          queryClient.invalidateQueries(['posts_list']);            │   │
│  │          // "posts_list" → Tüm listeler invalid edildi              │   │
│  │      }                                                             │   │
│  │  });                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Frontend cache temizlendi:                                                  │
│  - "post:id:123" → Silindi ✅                                                │
│  - "posts_list" → Tüm sorgular invalid edildi ✅                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  6. RESPONSE DÖNDÜRME                                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  HTTP 200 OK                                                        │   │
│  │  {                                                                 │   │
│  │    "success": true                                                 │   │
│  │  }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     ✅ KULLANICIYA RESPONSE DÖNDÜ                           │
│                                                                             │
│  Sonraki request'lerde:                                                       │
│  - GET /api/v1/posts/123 → Cache miss → DB'den güncel veri ✅                 │
│  - GET /api/v1/posts → Cache miss (v2) → DB'den güncel liste ✅               │
│  - Frontend cache boş → Backend'a request → Güncel veri ✅                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. DELETE İsteği - Silme

**Admin bir makaleyi sildiğinde (önceki detaylı anlatımın özeti):**

```
DeletePostCommandHandler
  ↓
1. Soft delete (IsDeleted = true, DeletedAt = DateTime.UtcNow)
  ↓
2. DB update (UPDATE Posts SET IsDeleted = true WHERE Id = ...)
  ↓
3. Cache invalidation (3 adım):
   - RemoveAsync(PostCacheKeys.ById(post.Id))
     → SignalR broadcast: KeyRemoved("post:id:123")
   - RemoveAsync(PostCacheKeys.BySlug(post.Slug))
     → SignalR broadcast: KeyRemoved("post:slug:...")
   - RotateGroupVersionAsync(PostCacheKeys.ListGroup)
     → SignalR broadcast: GroupRotated("posts_list")
  ↓
4. Frontend cache invalidation (use-cache-sync)
   - queryClient.invalidateQueries(["post:id:123"])
   - queryClient.invalidateQueries(["posts_list"])
  ↓
5. Sonraki GET /api/v1/posts request'inde:
   - Cache miss (v2)
   - DB sorgusu: WHERE IsDeleted = false
   - Silinen post listelenmez ✅
```

**Detaylı anlatım için önceki mesajı inceleyin.**

---

## ÖZET TABLOSU

| İstek Tipi | Cache'lenebilir? | Cache Stratejisi | Invalidation Gerekli? | SignalR Bildirimi? | Performans |
|------------|------------------|------------------|----------------------|-------------------|------------|
| **GET (Query)** | ✅ Evet | L1→L2→DB (SWR) | ❌ Hayır | ❌ Hayır | < 1ms (hit), ~550ms (miss) |
| **GET (Query - SWR Fresh)** | ✅ Evet | L2 hit (fresh) | ❌ Hayır | ❌ Hayır | ~15ms (37x faster!) |
| **GET (Query - SWR Stale)** | ✅ Evet | L2 hit (stale) + BG refresh | ❌ Hayır | ❌ Hayır | < 1ms + background refresh |
| **POST (Create)** | ❌ Hayır | Yok | ✅ Grup versiyonu | ✅ Evet (GroupRotated) | ~100ms (DB insert) |
| **PUT/PATCH (Update)** | ❌ Hayır | Yok | ✅ Key + Grup | ✅ Evet (KeyRemoved + GroupRotated) | ~100ms (DB update) |
| **DELETE (Delete)** | ❌ Hayır | Yok | ✅ Key + Grup | ✅ Evet (KeyRemoved + GroupRotated) | ~100ms (DB update) |

---

## KRİTİK NOKTALAR

### 1. Sadece Query'ler Cache'lenir

```csharp
// ✅ Cache'lenebilir (ICacheableQuery implement eder)
public class GetPostsListQueryRequest : IRequest<>, ICacheableQuery
{
    public string CacheKey => "posts-list-1-10...";
    public string? CacheGroup => "posts_list";
    public TimeSpan? CacheDuration => TimeSpan.FromMinutes(10);
    public bool UseStaleWhileRevalidate => true;
    public double SwrSoftRatio => 0.5;
}

// ❌ Cache'lenemez (Command - ICacheableQuery yok)
public class CreatePostCommandRequest : IRequest<>
{
    // Cache properties YOK
}
```

**Kural:**
- ✅ **Query** (okuma) → `ICacheableQuery` → Cache'lenir
- ❌ **Command** (yazma) → Interface yok → Cache'lenmez

---

### 2. L1 ve L2 Cache Farkı

| Özellik | L1 (IMemoryCache) | L2 (Redis) |
|---------|-------------------|------------|
| **Konum** | Instance başına (RAM) | Merkezi (Redis sunucusu) |
| **Erişim Hızı** | < 1ms (network yok) | 5-15ms (network round-trip) |
| **TTL** | L2'nin 1/10'i (min 10sn, max 2dk) | Tam TTL (5-10 dakika) |
| **Paylaşım** | Instance başına (paylaşımsız) | Tüm instance'lar arasında |
| **Amaç** | Ultra hızlı erişim | Cross-instance consistency |

**Örnek TTL Hesaplaması:**
```
L2 TTL = 10 dakika
L1 TTL = min(10sn, 10dk / 10) = 10 saniye

L2 TTL = 1 dakika
L1 TTL = min(10sn, 1dk / 10) = 10 saniye (minimum)

L2 TTL = 30 dakika
L1 TTL = min(10sn, 30dk / 10) = min(10sn, 3dk) = 10 saniye (maximum: 2dk)
```

---

### 3. SWR (Stale-While-Revalidate) Zaman Çizelgesi

**Konfigürasyon:**
```csharp
CacheDuration = TimeSpan.FromMinutes(10);  // Hard expiration
SwrSoftRatio = 0.5;                       // Soft = 50% of hard
```

**Zaman Çizelgesi:**
```
0-5 dk:    FRESH ✅
           - Hemen döndür
           - Background refresh yok
           - Response: < 1ms (L1) veya ~15ms (L2)

5-10 dk:   STALE ⚠️
           - Hemen döndür (stale data)
           - Background refresh tetiklendi
           - Response: < 1ms (L1) veya ~15ms (L2)
           - Bir sonraki request'te fresh data

10+ dk:   EXPIRED ❌
           - Cache miss
           - Factory çalıştır (DB sorgusu)
           - Response: ~550ms
           - Yeni cache entry oluştur
```

**Performans Karşılaştırması:**
| Senaryo | Response Time | Speedup |
|---------|---------------|---------|
| DB Query (no cache) | ~550ms | 1x |
| L2 Hit (fresh) | ~15ms | 37x |
| L1 Hit (fresh) | < 1ms | 550x |
| L2 Hit (stale) | ~15ms | 37x + background refresh |
| L1 Hit (stale) | < 1ms | 550x + background refresh |

---

### 4. Otomatik SignalR Bildirimi (Magic Hooks! 🪄)

**Command handler'larda manuel SignalR çağrısı GEREKMEZ!**

```csharp
// Command handler
public async Task<Response> Handle(Request request, ct)
{
    // İşlemi yap
    await _repository.UpdateAsync(post);
    await _unitOfWork.SaveChangesAsync(ct);

    // ❌ MANUEL SIGNALR GEREKMEZ!
    // await _signalR.SendAsync("CacheInvalidated", ...);

    // ✅ Otomatik hook tetiklenir
    await _cacheService.RemoveAsync(key);
    // ↓
    // CacheService.OnKeyRemovedAsync() otomatik çağrılır
    // ↓
    // _notifier.NotifyKeyRemovedAsync() otomatik çağrılır
    // ↓
    // SignalR broadcast otomatik gider!

    return new Response { Success = true };
}
```

**Hook Zinciri:**
```
Command Handler
  ↓
cacheService.RemoveAsync(key)
  ↓
HybridCacheServiceBase.RemoveAsync()
  ↓
CacheService.OnKeyRemovedAsync(key)  ← Override edilmiş hook
  ↓
_notifier.NotifyKeyRemovedAsync(key)
  ↓
SignalR: Clients.All.SendAsync("CacheInvalidated", event)
  ↓
Frontend: use-cache-sync receives event
  ↓
queryClient.invalidateQueries([key])
```

---

### 5. Cache Stampede Koruması

**Problem:** 100 kullanıcı aynı anda aynı sayfaya talep geldiğinde?

**Çözüm:** Double-check pattern + Semaphore locks

```
Request 1 ─┐
Request 2 ─┤
Request 3 ─┤
...        ├──→ [L1 Miss] ──→ [L2 Miss] ──→ [KİLİT ALMA]
Request 99─┤                                       ┃
Request 100─                                       ┃
                                                   ┃
                            ┌──────────────────────┘
                            ▼
                    Request 1: Kilidi kazandı ✅
                    Factory'ı çalıştır (DB query)
                    Cache'e yaz
                    Kilidi serbest bırak
                            │
                            ├──────────────────────────┐
                            ▼                          ▼
                    Request 2-100: Double-check  L1 Hit 🎯
                    (Cache populate olmuş)
                    Kilit almaya gerek yok
                    Hemen cache'den dön
```

**Kod Akışı:**
```csharp
// 1. İlk kontrol (kilit yok)
if (L1Cache.TryGetValue(key, out value))
    return value;  // Fast path

// 2. Kilidi al
var keyLock = _locks.GetOrAdd(key, _ => new SemaphoreSlim(1, 1));
await keyLock.WaitAsync(timeout);

// 3. Double-check (kilit sonrası)
if (L1Cache.TryGetValue(key, out value))
{
    keyLock.Release();
    return value;  // Başka request populate etmiş
}

// 4. Factory çalıştır (sadece ilk request)
value = await factory();
await SetAsync(key, value);
keyLock.Release();
return value;
```

---

### 6. Versiyon Tabanlı Grup Invalidation

**Konsept:** Grup versiyonunu döndürerek tüm ilgili cache'leri invalid et

**Örnek:**
```
Versiyon v1 iken:
- posts_list:v1:list:page-1
- posts_list:v1:list:page-2
- posts_list:v1:list:page-3

Versiyon rotasyonu (v1 → v2):
- posts_list:v2:list:page-1  ← Yeni versiyon (geçerli)
- posts_list:v2:list:page-2  ← Yeni versiyon (geçerli)
- posts_list:v2:list:page-3  ← Yeni versiyon (geçerli)
- posts_list:v1:*            ← Eski versiyon (expires naturally)
```

**Avantajlar:**
- ✅ Tek atomik işlem (Redis INCR)
- ✅ Tüm instance'lar için geçerli
- ✅ Manual key silme gerektirmez
- ✅ Prefix-based scanning'e göre daha hızlı

**Kod:**
```csharp
// Redis'te atomik increment
var db = Redis.GetDatabase();
var newVersion = await db.StringIncrementAsync("cache_version:posts_list");
// v1 → v2 (atomic)

// Sonraki request'te:
var version = await _cacheService.GetGroupVersionAsync("posts_list");
// version = 2

cacheKey = $"posts_list:v{version}:posts-list-1-10...";
// "posts_list:v2:posts-list-1-10..."
```

---

## DOSYA REFERANSLARI

### Backend Dosyaları

| Dosya | Amaç |
|-------|------|
| `src/BlogApp.Server/BlogApp.Server.Application/Common/Behaviors/CachingBehavior.cs` | MediatR pipeline caching |
| `src/BlogApp.Server/BlogApp.Server.Infrastructure/Services/CacheService.cs` | Domain cache implementasyonu |
| `src/BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/Services/HybridCacheServiceBase.cs` | L1/L2 hibrit cache |
| `src/BlogApp.Server/BlogApp.Server.Application/Features/PostFeature/Constants/PostCacheKeys.cs` | Post cache anahtarları |
| `src/BlogApp.Server/BlogApp.Server.Api/Services/CacheInvalidationNotifier.cs` | SignalR notifier |
| `src/BlogApp.Server/BlogApp.Server.Api/Hubs/CacheInvalidationHub.cs` | SignalR hub |

### Frontend Dosyaları

| Dosya | Amaç |
|-------|------|
| `src/blogapp-web/src/hooks/use-cache-sync.ts` | Cache senkronizasyon hook'u |
| `src/blogapp-web/src/components/cache-sync-provider.tsx` | Cache sync context provider |

---

**Son Güncelleme:** 2026-02-01
**Versiyon:** 1.0
