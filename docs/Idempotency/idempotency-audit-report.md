# Idempotency Audit Raporu

**Tarih:** 2026-03-14
**Proje:** MrBekoXBlogApp (Full Stack)
**Kapsam:** Frontend, Backend, AI Agent Service

## 2026-03-14 Status Update

This report was revalidated against the current codebase on 2026-03-14.

Fixed in code:

- `POST /api/v1/auth/login`, `register`, `refresh-token`, and `logout` now require `Idempotency-Key`.
- `.NET POST /api/admin/quarantine/replay` and FastAPI `POST /admin/quarantine/replay` now use strict idempotency with cached replay support.
- Frontend auth flows now propagate `Idempotency-Key` consistently, including automatic refresh.
- Backend cleanup now removes completed and failed idempotency and inbox rows older than 30 days.
- `.NET` response replay now stores replayable headers together with cached bodies.
- Sync write endpoints now use a shared transaction scope for idempotency begin, business mutation, and finalization, preventing committed orphan `Processing` rows after unexpected failures.

Reclassified findings:

- SEO finding: false positive because the current HTTP SEO surface is read-only.
- Comments finding: out of scope for idempotency because the backend mutation endpoints are absent.
- Stage-cache TTL finding: false positive because current TTL already exceeds worker operation timeout.

---

## Yönetici Özeti

Bu proje, uçtan uca idempotency için **kapsamlı bir implementasyona sahiptir**. Frontend'den veritabanına kadar her katmanda idempotency mekanizmaları bulunmaktadır. Ancak bazı endpoint'lerde (Auth, Admin, SEO) idempotency eksikliği tespit edilmiştir.

| Katman | Genel Durum |
|--------|-------------|
| Frontend | ✅ İyi |
| Backend API | ✅ İyi |
| Veritabanı | ✅ İyi |
| AI Agent Service | ✅ Çok İyi |
| Auth/Admin/SEO | ⚠️ Eksik |

---

## 1. Frontend Idempotency Durumu

### 1.1 Idempotency-Key HeaderImplementasyonu

**Dosya:** `src/blogapp-web/src/lib/idempotency.ts`

```typescript
export function createOperationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `op_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export function withIdempotencyHeader(
  operationId: string,
  config: AxiosRequestConfig = {}
): AxiosRequestConfig {
  return {
    ...config,
    headers: {
      ...(config.headers ?? {}),
      'Idempotency-Key': operationId,
    },
  };
}
```

**Kullanılan Endpoint'ler:**
- Posts: create, update, delete, publish, archive, unpublish
- Categories: create, update, delete
- Tags: create, delete
- Comments: create
- AI: generateTitle, generateExcerpt, generateTags, generateSeoDescription, improveContent
- Chat: sendMessage
- Media: uploadImage, uploadImages, deleteImage

### 1.2 Form Submission Önleme

```typescript
const [isSubmitting, setIsSubmitting] = React.useState(false);

const onSubmit = async (data: GuestFormData | AuthFormData) => {
  setIsSubmitting(true);
  try {
    // API call
  } finally {
    setIsSubmitting(false);
  }
};

// Button disabled state
<button type="submit" disabled={isSubmitting}>
```

### 1.3 Optimistic Update Rollback

**Dosya:** `src/blogapp-web/src/stores/categories-store.ts`

```typescript
deleteCategory: async (id: string) => {
  const previousCategories = get().categories;
  set((state) => ({
    categories: state.categories.filter((c) => c.id !== id),
  }));

  try {
    const response = await categoriesApi.delete(id);
    if (response.success) {
      await get().fetchCategories(true);
      return true;
    } else {
      set({ categories: previousCategories, error: response.message });
      return false;
    }
  } catch (error) {
    set({ categories: previousCategories, error: message });
    return false;
  }
},
```

### 1.4 AI Analysis Tekrar Kontrolü

```typescript
const completedOperationIdsRef = useRef<Set<string>>(new Set());

const handleAiAnalysisCompleted = (rawEvent: Record<string, unknown>) => {
  if (event.operationId && completedOperationIdsRef.current.has(event.operationId)) {
    return; // Zaten işlenmiş
  }
  completedOperationIdsRef.current.add(event.operationId);
};
```

### 1.5 Test Coverage

**Dosya:** `src/blogapp-web/src/lib/__tests__/idempotency.test.js`

```typescript
it('preserves existing request configuration while injecting the header', () => {
  const config = withIdempotencyHeader('op-123', {
    params: { retry: true },
    headers: { Authorization: 'Bearer token' },
  });
  expect(config.headers['Idempotency-Key']).toBe('op-123');
});
```

---

## 2. Backend Idempotency Durumu

### 2.1 IdempotencyEndpointHelper

**Dosya:** `src/BlogApp.Server/BlogApp.Server.Api/Endpoints/IdempotencyEndpointHelper.cs`

```csharp
var headerOperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault();

if (requireHeader && string.IsNullOrWhiteSpace(headerOperationId))
{
    errorResult = Results.BadRequest(ApiResponse<object>.FailureResult("Idempotency-Key header is required."));
    return false;
}
```

### 2.2 IdempotencyService

**Dosya:** `src/BlogApp.Server/BlogApp.Server.Infrastructure/Services/IdempotencyService.cs`

```csharp
public async Task<IdempotencyStartResult> BeginRequestAsync(
    IdempotencyStartRequest request,
    CancellationToken cancellationToken = default)
{
    var existing = await context.IdempotencyRecords
        .SingleOrDefaultAsync(
            x => x.EndpointName == request.EndpointName && x.OperationId == request.OperationId,
            cancellationToken);

    if (existing is not null)
    {
        return BuildExistingStartResult(existing, request.RequestHash);
    }

    var record = new IdempotencyRecord { ... };
    context.IdempotencyRecords.Add(record);

    try
    {
        await context.SaveChangesAsync(cancellationToken);
        return new IdempotencyStartResult(IdempotencyStartState.Started, record);
    }
    catch (DbUpdateException ex)
    {
        if (!IsUniqueConstraintViolation(ex)) throw;
        existing = await context.IdempotencyRecords
            .SingleOrDefaultAsync(...);
        return BuildExistingStartResult(existing, request.RequestHash);
    }
}
```

### 2.3 Veritabanı Unique Constraint

**Dosya:** `src/BlogApp.Server/BlogApp.Server.Infrastructure/Persistence/Configurations/IdempotencyRecordConfiguration.cs`

```csharp
builder.HasIndex(x => new { x.EndpointName, x.OperationId })
    .IsUnique()
    .HasDatabaseName("IX_idempotency_records_endpoint_operation")
    .HasFilter("\"IsDeleted\" = false");
```

### 2.4 IdempotencyRecord Entity

```csharp
public class IdempotencyRecord : BaseAuditableEntity
{
    public string EndpointName { get; set; }
    public string OperationId { get; set; }
    public string RequestHash { get; set; }
    public string CorrelationId { get; set; }
    public IdempotencyRecordStatus Status { get; set; }  // Processing/Completed/Failed
    public int? AcceptedHttpStatus { get; set; }
    public string? AcceptedResponseJson { get; set; }
    public int? FinalHttpStatus { get; set; }
    public string? FinalResponseJson { get; set; }
    public Guid? UserId { get; set; }
    public string? ResourceId { get; set; }
}
```

### 2.5 Consumer Inbox (Mesaj İşleme Idempotency)

```csharp
public class ConsumerInboxMessage : BaseAuditableEntity
{
    public string ConsumerName { get; set; }
    public string OperationId { get; set; }
    public Guid? MessageId { get; set; }
    public string? CorrelationId { get; set; }
    public ConsumerInboxStatus Status { get; set; }
}
```

---

## 3. AI Agent Service Idempotency Durumu

### 3.1 Redis Operation Claim

**Dosya:** `src/services/ai-agent-service/app/infrastructure/cache/redis_adapter.py`

```python
async def claim_operation(
    self,
    consumer_name: str,
    operation_id: str,
    message_id: str,
    correlation_id: str | None = None,
    lock_ttl_seconds: int = 300,
) -> dict[str, Any]:
    key = self._operation_key(consumer_name, operation_id)
    for _ in range(5):
        async with self.client.pipeline(transaction=True) as pipe:
            await pipe.watch(key)
            existing = await pipe.hgetall(key)

            if existing:
                if status == "completed":
                    parsed["state"] = "duplicate_completed"
                    return parsed
                if status == "failed":
                    parsed["state"] = "duplicate_failed"
                    return parsed
                if locked_until > now_ts:
                    parsed["state"] = "duplicate_processing"
                    return parsed
```

### 3.2 Stage Cache (Ara Sonuç Önbellekleme)

**Dosya:** `src/services/ai-agent-service/app/messaging/consumer.py`

```python
@staticmethod
def _stage_cache_key(operation_id: str, stage: str) -> str:
    return f"idempotency:stage:{OPERATION_CONSUMER_NAME}:{operation_id}:{stage}"

async def _get_stage_cache(self, operation_id: str, stage: str) -> dict[str, Any] | None:
    cached = await self._cache.get_json(self._stage_cache_key(operation_id, stage))
    return cached

async def _set_stage_cache(self, operation_id: str, stage: str, value: dict[str, Any]) -> None:
    await self._cache.set_json(
        self._stage_cache_key(operation_id, stage),
        value,
        ttl_seconds=settings.worker_stage_cache_ttl_seconds,
    )
```

**Stage'ler:**
- `generation.result` - AI generation sonuçları
- `chat.result` - Chat yanıtları
- `analysis.full` - Tam analiz sonuçları
- `analysis.indexing` - Indexing durumu

### 3.3 Distributed Lock

```python
async def acquire_lock(self, resource_id: str, ttl_seconds: int = 300) -> CacheLockLease | None:
    key = f"lock:resource:{resource_id}"
    token = secrets.token_urlsafe(32)
    result = await self.client.set(key, token, nx=True, ex=ttl_seconds)
    return CacheLockLease(resource_id=resource_id, token=token) if result else None
```

### 3.4 Prometheus Metrikleri

```python
idempotency_replays_total = Counter(
    "ai_idempotency_replays_total",
    "Total idempotency replays by source",
    ["source"],
)

stage_cache_operations_total = Counter(
    "ai_stage_cache_operations_total",
    "Stage cache hits, misses, and stores",
    ["stage", "outcome"],
)
```

---

## 4. Endpoint Bazında Durum

| Endpoint Dosyası | Idempotency Durumu | Açıklama |
|------------------|-------------------|-----------|
| PostsEndpoints.cs | ✅ VAR | Tüm mutation'lar |
| CategoriesEndpoints.cs | ✅ VAR | Tüm mutation'lar |
| TagsEndpoints.cs | ✅ VAR | Tüm mutation'lar |
| MediaEndpoints.cs | ✅ VAR | Tüm mutation'lar |
| ChatEndpoints.cs | ✅ VAR | operationId ile |
| AiEndpoints.cs | ✅ VAR | operationId ile |
| AuthEndpoints.cs | ❌ YOK | Login/Register |
| AdminEndpoints.cs | ❌ YOK | Admin işlemleri |
| SeoEndpoints.cs | ❌ YOK | SEO işlemleri |

---

## 5. Öneriler

### 5.1 Yüksek Öncelik

1. **AuthEndpoints'e Idempotency Eklenmesi**
   - Login/Register endpoint'leri tekrar isteklere karşı korumasız
   - Özellikle register'da aynı email ile tekrarlanan istekler sorun olabilir
   - `requireIdempotencyKey: true` olarak güncellenmeli

2. **AdminEndpoints'e Idempotency Eklenmesi**
   - Admin panel mutation'ları korumasız
   - Sistem yönetimi işlemleri için kritik

### 5.2 Orta Öncelik

3. **Frontend Optimistic Update Genişletme**
   - Şu an sadece delete'te rollback var
   - Create/update için de optimistic rollback eklenebilir

4. **Retry Mekanizmasında Operation ID Koruma**
   - Retry edilen isteklerde aynı operation ID kullanılmalı

### 5.3 Düşük Öncelik

5. **SeoEndpoints İnceleme**
   - Okuma işlemleri idempotency gerektirmez
   - Eğer mutation varsa eklenmeli

---

## 6. Sonuç

| Metrik | Değer |
|--------|-------|
| Toplam Katman | 4 |
| Tamamlanmış | 3.5 |
| Eksik | 0.5 |
| Tamamlanma Oranı | ~87% |

Proje, modern bir idempotency implementasyonuna sahiptir ve üretim kullanımı için uygundur. Auth ve Admin endpoint'lerinin güncellenmesi önerilir.
