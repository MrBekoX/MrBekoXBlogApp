# Uçtan Uca Idempotency Denetim Raporu

**Tarih:** 2026-03-14
**Kapsam:** Frontend (Next.js) · Backend (.NET) · AI Agent Service (Python/FastAPI)
**Genel Sonuç:** ⚠️ **PARTIAL** — Kritik açıklar mevcut, temel iş akışları korunuyor

## 2026-03-14 Status Update

This audit was revalidated against the current codebase on 2026-03-14.

Fixed in code:

- Auth mutations now enforce `Idempotency-Key` on `POST /api/v1/auth/login`, `register`, `refresh-token`, and `logout`.
- `.NET POST /api/admin/quarantine/replay` and FastAPI `POST /admin/quarantine/replay` now reject missing keys, detect payload conflicts, and replay cached responses for duplicates.
- Frontend auth requests, including the automatic refresh flow, now always send `Idempotency-Key`.
- Backend cleanup now deletes completed or failed `idempotency_records` and `consumer_inbox_messages` older than 30 days.
- `.NET` response replay now persists replayable headers such as `Set-Cookie` and `Location`.
- Sync write endpoints now keep idempotency start, business mutation, and finalization inside a shared transaction scope so unexpected failures do not leave committed orphan `Processing` rows.

Reclassified findings:

- SEO endpoints: false positive because the current HTTP surface is read-only.
- Comments item: out of scope for idempotency because the backend mutation endpoints are absent.
- AI stage-cache TTL item: false positive because current TTL already exceeds worker operation timeout.

---

## Yönetici Özeti

| Katman | Durum | Kısa Değerlendirme |
|--------|-------|-------------------|
| **Backend (.NET)** | ⚠️ PARTIAL | Content/Media/Tag/Category tam korumalı; Auth ve Admin endpoint'leri açık |
| **Frontend (Next.js)** | ⚠️ PARTIAL | API header entegrasyonu iyi; Comments ve form double-submit açıkları var |
| **AI Agent Service** | ✅ PASS | RabbitMQ consumer seviyesinde production-ready distributed idempotency |

---

## 1. Backend (.NET) — Detaylı Bulgular

### 1.1 Domain Modeli

`IdempotencyRecord` entity'si kapsamlı biçimde modellenmiş:

```
EndpointName + OperationId  →  Composite Unique Constraint (PostgreSQL)
RequestHash                 →  SHA256 — farklı payload ile aynı key → 409 Conflict
CorrelationId               →  Async işlemlerde completion tracking
FinalResponseJson (JSONB)   →  Tam response cache — replay için
Status                      →  Processing | Completed | Failed
```

**Eksik:** TTL/Expiry alanı yok → tablo zamanla şişer.

### 1.2 State Machine (IdempotencyStartState)

```
İstek gelir
    │
    ├─ Kayıt YOK          → Started       → İşlemi yürüt, sonucu kaydet
    ├─ Status=Processing  → 409 Conflict  → "Zaten işleniyor"
    ├─ Status=Completed   → 200/201       → Cached response dön
    ├─ Status=Failed      → 422           → Önceki hata bilgisi dön
    └─ Farklı RequestHash → 409 Conflict  → "Payload uyuşmazlığı"
```

### 1.3 Korunan Endpoint'ler ✅

| Endpoint | HTTP | requireIdempotencyKey |
|----------|------|-----------------------|
| CreatePost | POST | **true** |
| UpdatePost | PUT | **true** |
| DeletePost | DELETE | **true** |
| UnpublishPost / ArchivePost | POST | **true** |
| UploadImage / UploadImages | POST | **true** |
| DeleteFile | DELETE | **true** |
| CreateCategory / UpdateCategory / DeleteCategory | POST/PUT/DELETE | **true** |
| CreateTag / DeleteTag | POST/DELETE | **true** |

### 1.4 Korunmayan veya Zayıf Endpoint'ler ⚠️

| Endpoint | Durum | Risk |
|----------|-------|------|
| `POST /auth/register` | ❌ İdempotency yok | 🔴 **CRITICAL** — Duplicate kullanıcı oluşturma |
| `POST /auth/login` | ❌ İdempotency yok | 🔴 **CRITICAL** — Çift oturum/token riski |
| `POST /auth/refresh-token` | ❌ İdempotency yok | 🔴 HIGH |
| `POST /admin/quarantine/replay` | ❌ İdempotency yok | 🔴 **CRITICAL** — Double-replay → sonsuz döngü |
| `POST /posts/{id}/publish` | ⚠️ `requireHeader: false` | 🟡 MEDIUM |
| `POST /posts/{id}/save-draft` | ⚠️ `requireHeader: false` | 🟡 MEDIUM |
| Tüm AI endpoint'leri (11 adet) | ⚠️ `requireHeader: false` | 🟡 MEDIUM — Async dispatcher kısmen telafi ediyor |
| `POST /chat/message` | ⚠️ `requireHeader: false` | 🟡 MEDIUM |

### 1.5 Consumer Inbox (Mesaj Idempotency)

RabbitMQ consumer mesajları için `ConsumerInboxMessage` tablosu ile tam deduplication sağlanıyor:

```sql
UNIQUE (ConsumerName, OperationId) WHERE IsDeleted = false
```

Aynı `operationId` ile gelen tekrar mesaj → `DuplicateCompleted` / `DuplicateProcessing` state dönüyor, yeniden işlenmiyor. ✅

### 1.6 DB Schema

```sql
-- idempotency_records
UNIQUE IX: (EndpointName, OperationId) WHERE IsDeleted = false
INDEX:     (CorrelationId)
INDEX:     (Status, CreatedAt)   -- Cleanup için

-- consumer_inbox_messages
UNIQUE IX: (ConsumerName, OperationId) WHERE IsDeleted = false

-- outbox_messages
UNIQUE IX: (MessageId) WHERE IsDeleted = false
```

**Eksik:** Otomatik TTL/purge job yok. Tamamlanan kayıtlar silinmiyor → uzun vadede performans riski.

---

## 2. Frontend (Next.js) — Detaylı Bulgular

### 2.1 Idempotency Key Üretimi

**Dosya:** `src/blogapp-web/src/lib/idempotency.ts`

```typescript
export function createOperationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();           // UUID v4 — primary
  }
  return `op_${Date.now()}_${Math.random().toString(16).slice(2)}`;  // Fallback
}
```

Her request için yeni UUID üretiliyor — düzgün. ✅

### 2.2 API Header Entegrasyonu

**Dosya:** `src/blogapp-web/src/lib/api.ts`

```typescript
export function withIdempotencyHeader(operationId: string, config = {}) {
  return { ...config, headers: { ...config.headers, 'Idempotency-Key': operationId } };
}
```

`Idempotency-Key` header'ı doğru gönderiliyor. Backend, header ile body'deki `operationId`'nin eşleşmesini kontrol ediyor. ✅

### 2.3 UI-Level Korumalar

| Bileşen | Koruma Mekanizması | Durum |
|---------|-------------------|-------|
| Post form butonları | `disabled={isLoading}` | ✅ |
| Comment form | `disabled={isSubmitting}` (local state) | ✅ |
| Chat input | `disabled={!input.trim() \|\| isLoading}` | ✅ |
| AI operasyon butonları | `pendingRef` ile per-op tracking | ✅ |

### 2.4 AI Operasyon Hook'u (Async)

**Dosya:** `src/blogapp-web/src/hooks/use-authoring-ai-operations.ts`

```typescript
const pendingRef = useRef<Map<string, PendingOperation>>(new Map());
// Her operasyon için Promise, timeout (130s), operationId remapping destekli
```

Sophisticated async tracking. ✅

### 2.5 Eksik/Zayıf Noktalar

| Sorun | Konum | Risk |
|-------|-------|------|
| Comment oluşturma — `operationId` API'ye iletilmiyor | `comment-form.tsx:65` | 🟡 MEDIUM — Double yorum riski |
| Store seviyesinde pending operation deduplication yok | `posts-store.ts` | 🟡 MEDIUM |
| Network hatası sonrası yeni `operationId` üretiliyor (retry semantics kırık) | `api.ts` | 🟡 MEDIUM |
| Form double-submit için client-side `pendingOperationId` takibi yok | Genel | 🟡 MEDIUM |

---

## 3. AI Agent Service (Python) — Detaylı Bulgular

### 3.1 Genel Mimari

HTTP endpoint'ler **sadece read-only** (health, metrics, admin stats). Gerçek idempotency gereksinimi **RabbitMQ consumer katmanında** uygulanmış. Bu bilinçli bir mimari tercihtir.

### 3.2 Distributed Operation Claiming

**Dosya:** `app/infrastructure/cache/redis_adapter.py:111-193`

**Redis WATCH/MULTI/EXEC (Optimistic Locking):**

```python
async def claim_operation(consumer_name, operation_id, message_id, ...):
    # Mevcut durum kontrolü
    # → "duplicate_completed": Daha önce başarıyla bitti → cached response dön
    # → "duplicate_failed":    Daha önce hata aldı → hata state dön
    # → "duplicate_processing": Şu an işleniyor (lock geçerli) → bekle
    # → "claimed":             Yeni işlem başlatıldı
    # → "reclaimed":           Stale lock geri alındı, yeniden işle
```

5 deneme + stale lock reclaim mekanizması. ✅

### 3.3 Stage Cache (Multi-Level Idempotency)

**Dosya:** `app/messaging/consumer.py:448-473`

| Stage Cache Key | Amaç | TTL |
|----------------|------|-----|
| `generation.result` | Başlık/özet/etiket üretimi | `worker_stage_cache_ttl_seconds` |
| `chat.result` | Chat yanıtı | Aynı |
| `analysis.indexing` | Makale indeksleme | Aynı |
| `analysis.full` | Tam analiz sonucu | Aynı |

Timeout sonrası retry'da ara sonuçlar cache'den dönüyor → duplicate LLM inference yok. ✅

### 3.4 Response Persistence & Republish

```python
# Tamamlanan operasyonun yanıtı Redis'e yazılıyor
await self._cache.store_operation_response(consumer_name, operation_id, response, routing_key)

# Duplicate gelince saklanmış yanıt yeniden yayınlanıyor
await self._republish_stored_response(operation_id, claim, correlation_id, message_id)
```

✅

### 3.5 Redis Key Yapısı

| Key Pattern | Amaç | TTL |
|------------|------|-----|
| `processed:event:{messageId}` | Message-level duplicate detection | 86400s (24h) |
| `inbox:{consumer}:{operationId}` | Operation state | `worker_operation_retention_seconds` |
| `idempotency:stage:{consumer}:{operationId}:{stage}` | Ara sonuç cache | `worker_stage_cache_ttl_seconds` |
| `lock:resource:{resourceId}` | Makale işleme distributed lock | 300s |
| `message:{messageId}:operation` | Message → Operation mapping | `max(lock_ttl*10, retention)` |

### 3.6 Eksik/Zayıf Noktalar

| Sorun | Konum | Risk |
|-------|-------|------|
| `POST /admin/quarantine/replay` idempotency yok | `admin.py:79-99` | 🔴 HIGH |
| Chat deduplication sadece `messageId` tabanlı; `sessionId`+içerik tabanlı değil | `consumer.py:732` | 🟡 MEDIUM |
| Stage cache TTL, operation timeout'undan kısa olabilir | `consumer.py:471` | 🟡 MEDIUM |
| `lock_ttl_seconds` < `worker_operation_timeout_seconds` riski | `consumer.py:854-866` | 🟡 MEDIUM |

---

## 4. Uçtan Uca Akış Değerlendirmesi

### Senaryo 1: Post Oluşturma (Happy Path) ✅

```
Frontend                     Backend                         AI Agent
   │                            │                               │
   ├─ createOperationId()        │                               │
   ├─ POST /posts               │                               │
   │  Header: Idempotency-Key   │                               │
   │  Body:   operationId       │                               │
   │  ─────────────────────────►│                               │
   │                            ├─ TryBeginSyncRequest()        │
   │                            ├─ DB: INSERT idempotency_record│
   │                            ├─ İşlemi yürüt                │
   │                            ├─ DB: UPDATE → Completed       │
   │  ◄─────────────────────────┤  FinalResponseJson sakla      │
```

**Aynı key ile tekrar istek → Cached response döner. ✅**

### Senaryo 2: AI Content Generation (Async) ✅

```
Frontend           Backend              RabbitMQ        AI Agent
   │                   │                    │               │
   ├─ POST /ai/gen-*   │                    │               │
   │  ────────────────►│                    │               │
   │                   ├─ DispatchAsync()   │               │
   │                   ├─ Publish event ───►│               │
   │◄── 202 Accepted   │                    │               │
   │                   │                    ├──────────────►│
   │                   │                    │  claim_op()   │
   │                   │                    │  LLM call     │
   │                   │                    │  cache result │
   │    SignalR event  │◄── Publish result──┤               │
   │◄──────────────────┤                    │               │
```

**Duplicate event → stage cache hit, republish. ✅**

### Senaryo 3: Auth Register (Açık) 🔴

```
Frontend                     Backend
   │                            │
   ├─ POST /auth/register ─────►│
   │                            ├─ Kullanıcı oluştur ✓
   │◄── 500 (network error)─────┤
   │                            │
   ├─ POST /auth/register ─────►│  (retry — aynı email)
   │                            ├─ Kullanıcı oluştur → DUPLICATE!
   │◄── 200 OK ─────────────────┤  (veya unique constraint hatası)
```

**Sonuç: Duplicate kayıt veya tutarsız durum. ❌**

---

## 5. Konsolide Risk Matrisi

| # | Sorun | Katman | Risk | Öncelik |
|---|-------|--------|------|---------|
| 1 | Auth endpoint'leri (register/login/refresh/logout) idempotency'siz | Backend | 🔴 CRITICAL | P0 |
| 2 | Admin quarantine/replay idempotency'siz | Backend + AI Agent | 🔴 HIGH | P0 |
| 3 | IdempotencyRecord TTL/purge job yok | Backend | 🟡 MEDIUM | P1 |
| 4 | Comment oluşturma idempotency'siz (frontend + backend) | Frontend + Backend | 🟡 MEDIUM | P1 |
| 5 | AI endpoints `requireIdempotencyKey: false` | Backend | 🟡 MEDIUM | P1 |
| 6 | Chat endpoint `requireIdempotencyKey: false` | Backend | 🟡 MEDIUM | P1 |
| 7 | Network hatası retry'da yeni `operationId` üretiliyor | Frontend | 🟡 MEDIUM | P1 |
| 8 | Stage cache TTL < operation timeout riski | AI Agent | 🟡 MEDIUM | P1 |
| 9 | Chat deduplication yalnızca `messageId` tabanlı | AI Agent | 🟡 MEDIUM | P2 |
| 10 | Store-level pending operation deduplication yok | Frontend | 🟢 LOW | P2 |

---

## 6. Tavsiye Edilen İyileştirmeler

### P0 — Acil (Bu sprint)

**1. Auth Endpoint'lerine İdempotency Ekle**

```csharp
// AuthEndpoints.cs — Register
group.MapPost("/register", async (RegisterRequest request, HttpContext ctx, ...) => {
    if (!IdempotencyEndpointHelper.TryResolveOperationId(
            ctx, request.OperationId, requireHeader: true,
            out var operationId, out var error))
        return error!;

    var (shouldProceed, earlyReturn, idempCtx) =
        await IdempotencyEndpointHelper.TryBeginSyncRequest(
            "auth.register", operationId, request, ctx, idempotencyService, ...);
    if (!shouldProceed) return earlyReturn!;
    // ...
});
```

**2. Admin Replay Endpoint'ine İdempotency Ekle**

```csharp
// AdminEndpoints.cs
group.MapPost("/quarantine/replay", async (ReplayRequest request, HttpContext ctx, ...) => {
    if (!IdempotencyEndpointHelper.TryResolveOperationId(
            ctx, request.OperationId, requireHeader: true,
            out var operationId, out var error))
        return error!;
    // ...
});
```

### P1 — Kısa Vadeli

**3. Idempotency Cleanup Hosted Service**

```csharp
// Tamamlanan ve 30 günden eski kayıtları sil
public class IdempotencyCleanupService : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            await context.IdempotencyRecords
                .Where(r => r.Status == IdempotencyStatus.Completed
                         && r.CompletedAt < DateTime.UtcNow.AddDays(-30))
                .ExecuteDeleteAsync(stoppingToken);
            await Task.Delay(TimeSpan.FromHours(1), stoppingToken);
        }
    }
}
```

**4. AI Endpoint'lerini Zorunlu Hale Getir**

```csharp
// AiEndpoints.cs — tüm AI endpoint'leri için
if (!IdempotencyEndpointHelper.TryResolveOperationId(
        httpContext, request.OperationId, requireHeader: true, ...))
```

**5. Frontend — Network Retry Sırasında Aynı `operationId` Kullan**

```typescript
// api.ts
async function requestWithRetry(fn: (operationId: string) => Promise<any>, maxRetries = 2) {
  const operationId = createOperationId();  // Tek seferlik üret
  for (let i = 0; i <= maxRetries; i++) {
    try {
      return await fn(operationId);          // Aynı key ile retry
    } catch (e) {
      if (i === maxRetries || !isNetworkError(e)) throw e;
    }
  }
}
```

**6. Stage Cache TTL'ini Operation Timeout'undan Büyük Yap**

```python
# config.py
worker_stage_cache_ttl_seconds: int = 900   # 15 min
worker_operation_timeout_seconds: int = 600  # 10 min
# Kural: stage_cache_ttl > operation_timeout
```

### P2 — Uzun Vadeli

- Redis önbellekleme katmanı ekle (yüksek frekanslı endpoint'ler için DB round-trip azalt)
- Idempotency conflict/replay metriklerini Prometheus'a ekle
- Comment create endpoint'ine tam idempotency uygula

---

## 7. Sonuç

```
Katman               Korunan        Açık           Genel
─────────────────────────────────────────────────────────
Backend Content Ops   10/10 (100%)   0              ✅ TAM
Backend Auth Ops       0/4   (0%)    4              🔴 KRİTİK
Backend Admin Ops      0/1   (0%)    1              🔴 KRİTİK
Backend AI/Chat Ops    0/12  (0%)*   0 (async)      🟡 KISMEN
Consumer Inbox         3/3  (100%)   0              ✅ TAM
AI Agent (RabbitMQ)   Full           1 (admin)      ✅ GÜÇLÜ
Frontend API Layer     Çoğu          Comments       🟡 KISMEN
─────────────────────────────────────────────────────────
* Async dispatcher tarafından kısmen telafi ediliyor
```

Sistemin temel içerik yönetimi iş akışları (post/media/category/tag) sağlam biçimde korunuyor. AI Agent servisi RabbitMQ katmanında production-ready distributed idempotency'ye sahip. Kritik açıklar Auth ve Admin operasyonlarında yoğunlaşıyor — bu iki alan P0 öncelikli müdahale gerektiriyor.
