# Mesaj Birikme Önleme — Priority Queue + Backpressure Gateway + Graceful Degradation

**Tarih:** 2026-03-18
**Durum:** Onaylandı
**Kısıtlar:** Tek AWS instance, tek Ollama, chat herkese açık, authoring sadece admin

---

## Problem

Tüm AI istekleri (chat, authoring, article analysis) tek `q.ai.analysis` kuyruğuna düşüyor. Canlıda:
- Birden fazla kullanıcı aynı anda chat yazarsa kuyruk büyür
- Ollama yavaşladığında/çöktüğünde mesajlar birikir
- Transient hatalar retry fırtınası yaratır
- Chat kullanıcıları gereksiz yere bekler

## Çözüm Özeti

6 katmanlı koruma:
1. 3 öncelikli kuyruk (chat / authoring / background) + TTL
2. Weighted fair scheduling (chat her zaman önce)
3. Backpressure gateway (backend tarafı kuyruk derinliği kontrolü)
4. Circuit breaker + graceful degradation (kuyruk bazlı farklı davranış)
5. Retry fırtınası önleme (limit + backoff + retry bütçesi)
6. Queue depth signaling (frontend bildirimi)

---

## Bölüm 1: RabbitMQ Topoloji Değişikliği

### Mevcut
- Tek kuyruk `q.ai.analysis` — tüm event tipleri aynı kuyruğa düşüyor
- `q.chat.requests` sabiti `MessagingConstants.QueueNames` altında tanımlı ama şu an `q.ai.analysis` ile aynı topolojide kullanılıyor

### Yeni Topoloji

```
blog.events (Direct Exchange)
  │
  ├─ chat.message.requested ──────────────► q.chat.requests
  │                                          (quorum, TTL: 60s, DLX: dlx.blog)
  │
  ├─ ai.title.generation.requested ──┐
  ├─ ai.excerpt.generation.requested ├────► q.ai.authoring
  ├─ ai.tags.generation.requested    │      (quorum, TTL: 300s, DLX: dlx.blog)
  ├─ ai.seo.generation.requested     │
  ├─ ai.content.improvement.requested┘
  │
  ├─ article.created ────────────────┐
  ├─ article.published               │
  ├─ article.updated                 ├────► q.ai.background
  ├─ ai.summarize.requested          │      (quorum, TTL: 1800s, DLX: dlx.blog)
  ├─ ai.keywords.requested           │
  ├─ ai.sentiment.requested          │
  ├─ ai.geo-optimize.requested       │
  └─ ai.collect-sources.requested    ┘
```

**Not:** `ai.reading-time.requested` kuyruksuz kalır. `calculate_reading_time` senkron kelime sayma işlemidir, Ollama çağırmaz. Backend tarafında senkron hesaplanabilir veya kuyruğa hiç girmeden doğrudan yanıtlanabilir.

### Kuyruk İsimleri ve Constants Eşlemesi

`MessagingConstants.QueueNames` (C#) güncellemesi:

| Sabit | Mevcut Değer | Yeni Değer | Durum |
|-------|-------------|------------|-------|
| `ChatRequests` | `q.chat.requests` | `q.chat.requests` | Aynı kalır (mevcut isim kullanılır) |
| `AiAuthoring` | — | `q.ai.authoring` | Yeni eklenir |
| `AiBackground` | — | `q.ai.background` | Yeni eklenir |
| `AiAnalysis` | `q.ai.analysis` | `q.ai.analysis` | Deprecate, migration sonrası kaldırılır |

Python tarafı (`rabbitmq_adapter.py`) sabitleri:

```python
# Eski (tek kuyruk)
QUEUE_NAME = "q.ai.analysis"
ROUTING_KEYS = [...]  # tüm routing key'ler tek kuyruğa

# Yeni (3 kuyruk)
QUEUE_CHAT = "q.chat.requests"
QUEUE_AUTHORING = "q.ai.authoring"
QUEUE_BACKGROUND = "q.ai.background"

ROUTING_KEYS_CHAT = ["chat.message.requested"]
ROUTING_KEYS_AUTHORING = [
    "ai.title.generation.requested",
    "ai.excerpt.generation.requested",
    "ai.tags.generation.requested",
    "ai.seo.generation.requested",
    "ai.content.improvement.requested",
]
ROUTING_KEYS_BACKGROUND = [
    "article.created",
    "article.published",
    "article.updated",
    "ai.summarize.requested",
    "ai.keywords.requested",
    "ai.sentiment.requested",
    "ai.geo-optimize.requested",
    "ai.collect-sources.requested",
]
```

### Kuyruk Özellikleri

| Kuyruk | Prefetch | TTL | Amaç |
|--------|----------|-----|-------|
| `q.chat.requests` | 2 | 60s | Gerçek zamanlı chat |
| `q.ai.authoring` | 1 | 300s | Admin editör işlemleri |
| `q.ai.background` | 1 | 1800s | Arka plan analiz |

Prefetch değerleri slot sayılarıyla uyumlu: chat 2 slot = prefetch 2, authoring/background 1 shared slot = prefetch 1.

### DLQ Topolojisi

Her kuyruk için ayrı DLQ oluşturulur (kaynak ayırt edilebilsin):

| Kuyruk | DLQ | DLX |
|--------|-----|-----|
| `q.chat.requests` | `dlq.chat.requests` | `dlx.blog` |
| `q.ai.authoring` | `dlq.ai.authoring` | `dlx.blog` |
| `q.ai.background` | `dlq.ai.background` | `dlx.blog` |

Quarantine mekanizması (`q.ai.analysis.quarantine`) üç kuyruğun hepsini kapsar. Quarantine mesajında `x-original-queue` header'ı ile kaynak kuyruk belirtilir.

### TTL Mantığı
- Chat 60s: 1 dakikadan eski chat yanıtı kullanıcı için değersiz
- Authoring 300s: Admin hâlâ sayfada olabilir
- Background 1800s: Makale zaten kaydedilmiş, analiz acil değil

### TTL Expire + Circuit Open Edge Case
Chat mesajı kuyrukta iken TTL dolarsa DLX'e gider. Bu durumda kullanıcıya yanıt gitmez. Frontend tarafında chat isteği gönderildikten sonra 60s içinde yanıt gelmezse client-side timeout ile "Yanıt alınamadı, tekrar deneyin" mesajı gösterilir. DLX consumer'ı gerekmez.

### Migration Planı

1. **Aşama 1 — Yeni kuyruklar oluştur:** `_declare_topology()` güncellenir. 3 yeni kuyruk + binding'ler eklenir. Eski `q.ai.analysis` kuyruğu ve binding'leri korunur.
2. **Aşama 2 — Consumer'ı güncelle:** AI Agent 3 kuyruğu dinlemeye başlar. Eski kuyruğu da dinlemeye devam eder (geçiş dönemi).
3. **Aşama 3 — Backend publish güncelle:** Backend yeni routing key → kuyruk eşlemesini kullanmaya başlar. Eski kuyruğa mesaj gitmez.
4. **Aşama 4 — Temizlik:** Eski `q.ai.analysis` kuyruğu boşaldığında binding'ler kaldırılır, kuyruk silinir.

---

## Bölüm 2: Weighted Fair Scheduling (Consumer Tarafı)

### Uygulama Mekanizması

3 ayrı RabbitMQ consumer (aio_pika callback-based) + 1 global PriorityScheduler:

```
┌──────────────────────────────────────────────┐
│              PriorityScheduler                │
│  global_semaphore = Semaphore(3)              │
│  chat_semaphore   = Semaphore(2)              │
│  low_semaphore    = Semaphore(1)              │
│                                               │
│  Kuyruk callback geldiğinde:                  │
│  1. global_semaphore.acquire()                │
│  2. priority_semaphore.acquire() (chat veya   │
│     low — chat alınamazsa low dener)          │
│  3. İşle                                      │
│  4. Her iki semaphore release                 │
└──────────────────────────────────────────────┘
        ▲              ▲              ▲
   chat consumer  authoring consumer  background consumer
   (callback)     (callback)          (callback)
```

Her kuyruk kendi `queue.consume(callback)` ile dinlenir. Callback geldiğinde PriorityScheduler'a başvurur.

### Slot Dağılımı
- Toplam concurrent iş kapasitesi: **3 slot** (`global_semaphore(3)`)
- Chat: **2 dedicated slot** (`chat_semaphore(2)`)
- Authoring + Background: **1 shared slot** (`low_semaphore(1)`)

### Chat Patlaması
Chat callback geldiğinde `chat_semaphore` dolu ise `low_semaphore`'dan da slot alabilir (chat her zaman öncelikli). 10 kişi aynı anda chat yazarsa, 3 slot'un hepsi chat'e gider. Authoring ve background RabbitMQ prefetch tarafından engellenir (mesajlar kuyrukta bekler).

### Neden 3 Slot
Ollama tek GPU üzerinde çalışıyor. 3'ten fazla concurrent istek tüm yanıt sürelerini uzatır.

---

## Bölüm 3: Backpressure Gateway (Backend Tarafı)

### Mantık
Backend, RabbitMQ'ya mesaj göndermeden önce kuyruk derinliğini kontrol eder.

### Kurallar

| İstek Tipi | Kuyruk Derinliği | Davranış |
|------------|-----------------|----------|
| Chat | Herhangi | Her zaman kabul et |
| Authoring | > 10 | Frontend'e uyarı göster, isteği yine kuyruğa koy |
| Background | > 20 | Mesajı kuyruğa koyma, sessizce atla |

### Kuyruk Derinliği Veri Kaynağı — Redis

AI Agent `refresh_queue_stats()` her 3 kuyruk için derinliği Redis'e yazar:

```
Redis Key Format:
  queue:stats:q.chat.requests       → {"depth": 3, "updated_at": "..."}
  queue:stats:q.ai.authoring        → {"depth": 0, "updated_at": "..."}
  queue:stats:q.ai.background       → {"depth": 12, "updated_at": "..."}
  queue:stats:ollama:circuit_state   → "closed" | "open" | "half_open"

TTL: 30 saniye (stale veri önleme — TTL dolarsa backend "bilinmiyor" kabul eder ve publish'e izin verir)
```

Backend tarafında `IQueueDepthService` (yeni interface):
- `GetQueueDepthAsync(string queueName)` — Redis'ten okur
- Publish öncesi `MessagingExtensions` veya endpoint seviyesinde kontrol edilir
- Senkron, her publish öncesi çağrılır (Redis okuma < 1ms)

---

## Bölüm 4: Ollama Circuit Breaker + Graceful Degradation

### Circuit Breaker Durumları

| Durum | Koşul | Davranış |
|-------|-------|----------|
| Closed (normal) | Her şey çalışıyor | Mesajlar normal işlenir |
| Open (kesik) | Son 5 istekten 3'ü timeout/hata | Ollama'ya istek göndermeyi durdur, 30s bekle |
| Half-open (deneme) | 30s geçti | 1 test isteği gönder, başarılıysa closed'a dön |

### Circuit Open Durumunda Kuyruk Davranışları

| Kuyruk | Davranış |
|--------|----------|
| Chat | Fallback yanıt: "AI asistanı şu an yoğun" — mesaj işlenmiş sayılır, requeue yok |
| Authoring | nack + requeue, frontend'e "AI kullanılamıyor" sinyali (Redis üzerinden) |
| Background | nack + requeue, TTL dolana kadar bekle |

### Mevcut Circuit Breaker Entegrasyonu
Mevcut `app/core/circuit_breaker.py` genişletilir. Circuit state Redis'e yazılır (`queue:stats:ollama:circuit_state`). Consumer'daki `_process_node` çağrısından önce circuit state kontrol edilir. Kuyruk bazlı farklı davranış `PriorityScheduler` seviyesinde uygulanır — mesaj hangi kuyruktan geldiyse o kuyruğun degradation stratejisi uygulanır.

---

## Bölüm 5: Retry Fırtınası Önleme

### Kuyruk Bazlı Retry Limitleri

| Kuyruk | Max Retry | Limit aşılınca |
|--------|-----------|-----------------|
| Chat | 2 | Fallback yanıt dön |
| Authoring | 3 | Quarantine'e gönder |
| Background | 5 | Quarantine'e gönder |

### Exponential Backoff

Consumer tarafında `asyncio.sleep` ile (RabbitMQ delayed message plugin gerekmez):

```
Formül: delay = min(base * (4 ** (attempt - 1)), max_backoff)
base = 2s, max_backoff = 30s

1. retry: 2s
2. retry: 8s
3. retry: 30s (cap)
4. retry: 30s (cap)
5. retry: 30s (cap)
```

### Stage Cache Entegrasyonu
Mevcut `claim_operation` ve `_get_stage_cache` mekanizmaları korunur. Retry'da önceki adımda üretilen sonuç cache'de varsa Ollama'ya tekrar gidilmez.

### Retry Bütçesi

Toplam sistemde aynı anda en fazla **3 retry mesajı** işlenebilir.

Uygulama: Redis atomic counter `retry:inflight:count` (TTL: 5 dakika). Retry mesajı işlenmeye başlamadan önce counter artırılır, bitince azaltılır. Counter >= 3 ise retry mesajı nack + requeue yapılır. Retry mesajı tanımı: `x-delivery-count` header > 1 olan mesajlar.

---

## Bölüm 6: Queue Depth Signaling (Frontend)

### Chat Kullanıcıları
- Tahmini bekleme süresi: "Yanıt yaklaşık 15 saniye içinde gelecek"
- Circuit open: "AI asistanı şu an kullanılamıyor"
- Mevcut `ChatEventsHub` üzerinden
- Client-side 60s timeout: Yanıt gelmezse "Yanıt alınamadı, tekrar deneyin"

### Admin Panel
- Dashboard'da kuyruk durumu kartı (chat/authoring/background derinliği + Ollama durumu)
- Mevcut `AuthoringEventsHub` üzerinden
- Admin endpoint (`admin.queue.stats.requested`) 3 kuyruğun istatistiklerini döndürecek şekilde güncellenir

### Veri Akışı
AI Agent → Redis (kuyruk stats per queue + circuit state) → Backend → SignalR → Frontend
