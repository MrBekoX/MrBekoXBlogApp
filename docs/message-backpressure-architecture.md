# Mesaj Geri Baskı (Backpressure) Mimarisi

> **Tarih:** 2026-03-18
> **Kapsam:** AI Agent Service — RabbitMQ topolojisi, öncelikli zamanlayıcı, devre kesici ve yeniden deneme fırtınası önleme

---

## 1. Genel Bakış

### Problem

Başlangıç tasarımında tüm mesaj türleri (chat, AI authoring, AI background) tek bir kuyruğa (`q.ai.analysis`) yazılmaktaydı. Bu durum çeşitli sorunlara yol açtı:

- **Kuyruk birikimi:** Arka plan görevleri (makale analizi, sentiment vb.) gerçek zamanlı beklenen chat mesajlarını bloke ediyordu.
- **Eşit öncelik yok:** Kullanıcının anlık chat isteği, uzun süren bir makale özetleme görevi nedeniyle dakikalarca yanıt alamıyordu.
- **Kör yeniden denemeler:** Başarısız mesajlar herhangi bir bekleme süresi olmadan hemen yeniden kuyruğa alınıyor, Ollama servisine "retry fırtınası" yaşatıyordu.
- **Gözlenebilirlik eksikliği:** Frontend, kuyruk derinliğini veya devre durumunu bilemediğinden kullanıcıya anlamlı geri bildirim veremiyordu.

### Çözüm: 6 Katmanlı Yaklaşım

| Katman | Bileşen | Sorumluluk |
|--------|---------|------------|
| 1 | RabbitMQ Topolojisi | Üç ayrı kuyruk + öncelik yönlendirmesi |
| 2 | PriorityScheduler | Eşzamanlılık sınırı ve öncelik tahsisi |
| 3 | Backpressure Gateway | Backend tarafında akış kontrolü |
| 4 | Circuit Breaker | Ollama arızasına karşı devre kesici |
| 5 | Retry Bütçesi | Yeniden deneme fırtınasını önleme |
| 6 | Queue Depth Signaling | Frontend bilgilendirmesi |

---

## 2. RabbitMQ Topolojisi

### Exchange ve Kuyruk Yapısı

```
blog.events (Direct Exchange)
  │
  ├─ chat.message.requested ──────────► q.chat.requests   (TTL: 60s)
  │                                           │
  │                                           └─ [on expired/reject] ──► dlq.chat.requests
  │
  ├─ ai.*.generation.requested ───────► q.ai.authoring    (TTL: 300s)
  │   (excerpt, title, tags, seo,                │
  │    improve-content)                          └─ [on expired/reject] ──► dlq.ai.authoring
  │
  └─ article.*/ai.background.* ──────► q.ai.background   (TTL: 1800s)
      (summarize, sentiment,                     │
       keywords, sources,                        └─ [on expired/reject] ──► dlq.ai.background
       reading-time, geo-optimize)


  [Geçiş dönemi - kaldırılacak]
  └─ q.ai.analysis  (legacy, yalnızca migration süresince aktif)
```

### Routing Key Eşleştirme Tablosu

| Routing Key Deseni | Hedef Kuyruk | Açıklama |
|--------------------|--------------|----------|
| `chat.message.requested` | `q.chat.requests` | Gerçek zamanlı chat mesajları |
| `ai.excerpt.generation.requested` | `q.ai.authoring` | Excerpt üretimi |
| `ai.title.generation.requested` | `q.ai.authoring` | Başlık üretimi |
| `ai.tags.generation.requested` | `q.ai.authoring` | Tag üretimi |
| `ai.seo-description.generation.requested` | `q.ai.authoring` | SEO açıklama üretimi |
| `ai.content-improvement.generation.requested` | `q.ai.authoring` | İçerik geliştirme |
| `ai.summarize.requested` | `q.ai.background` | Makale özeti |
| `ai.sentiment.requested` | `q.ai.background` | Duygu analizi |
| `ai.keywords.requested` | `q.ai.background` | Anahtar kelime çıkarma |
| `ai.collect-sources.requested` | `q.ai.background` | Kaynak toplama |
| `ai.reading-time.requested` | `q.ai.background` | Okuma süresi hesaplama |
| `ai.geo-optimize.requested` | `q.ai.background` | Coğrafi optimizasyon |

---

## 3. Kuyruk Özellikleri Tablosu

| Kuyruk | Prefetch | TTL | Max Retry | DLQ |
|--------|----------|-----|-----------|-----|
| `q.chat.requests` | 2 | 60s | 2 | `dlq.chat.requests` |
| `q.ai.authoring` | 1 | 300s | 3 | `dlq.ai.authoring` |
| `q.ai.background` | 1 | 1800s | 5 | `dlq.ai.background` |

**Notlar:**

- **Prefetch:** RabbitMQ consumer'ın aynı anda kaç mesajı bellekte tutabileceğini sınırlar. `q.chat.requests` için 2 olmasının sebebi, chat'in 2 eşzamanlı slot hakkına sahip olmasıdır.
- **TTL:** Mesaj bu süre içinde tüketilmezse DLQ'ya yönlendirilir. Chat için 60 saniye, authoring için 5 dakika, background için 30 dakika.
- **Max Retry:** Başarısız işlem bu sayıda yeniden denendikten sonra DLQ'ya kalıcı olarak taşınır.
- **DLQ:** Dead Letter Queue — başarısız veya süresi dolan mesajlar için son durak. Manuel inceleme ve yeniden oynatma (replay) için kullanılır.

---

## 4. PriorityScheduler

### Çift Semafor Tasarımı

```
┌─────────────────────────────────────────────────────────┐
│                    PriorityScheduler                     │
│                                                         │
│   global_semaphore (max=3)  ◄── Ollama eşzamanlılık    │
│   ┌────────────────────┐        sınırı (tek GPU/CPU)   │
│   │  Slot 1  Slot 2  Slot 3 │                           │
│   └────────────────────┘                               │
│                                                         │
│   chat_semaphore (max=2)    ◄── Chat öncelik havuzu     │
│   low_semaphore  (max=1)    ◄── Background düşük öncelik│
│                                                         │
│   Chat isteği gelince:                                  │
│     → global_semaphore.acquire()                        │
│     → chat_semaphore.acquire()                          │
│       (doluysa low_semaphore'dan çal)                   │
│                                                         │
│   Authoring isteği gelince:                             │
│     → global_semaphore.acquire()                        │
│     → (authoring için özel semafor yok, global yeterli) │
│                                                         │
│   Background isteği gelince:                            │
│     → global_semaphore.acquire()                        │
│     → low_semaphore.acquire()                           │
└─────────────────────────────────────────────────────────┘
```

### Öncelik Sıralaması

```
YÜKSEK  ▲  Chat (real-time, kullanıcı bekliyor)
         │  Authoring (admin paneli, yarı-real-time)
DÜŞÜK   ▼  Background (arka plan, kullanıcı beklemez)
```

### Chat Taşma (Overflow) Mekanizması

Eğer `chat_semaphore` dolu olduğunda yeni bir chat isteği gelirse:

1. `low_semaphore`'dan bir slot "çalınır".
2. Bu sayede chat isteği background'u geciktirerek hemen işlenebilir.
3. Background görevi, `low_semaphore` serbest kalana kadar bekler.

**Toplam 3 eşzamanlı slot** Ollama'nın GPU/CPU kısıtı nedeniyle sabit tutulmuştur. Daha fazla eşzamanlı istek, model kalitesini ve yanıt sürelerini olumsuz etkiler.

---

## 5. Backpressure Gateway (Backend)

Backend, mesaj yayınlamadan önce kuyruk derinliğini Redis'ten kontrol eder ve akış kontrolü uygular.

### İstek Tipi — Davranış Matrisi

| İstek Tipi | Kuyruk Derinliği | Davranış |
|------------|-----------------|----------|
| Chat | Herhangi bir değer | Kabul et; devre açıksa (circuit open) 503 döndür |
| Authoring | ≤ 10 | Normal kabul et |
| Authoring | > 10 | Kabul et + yanıtta `isBackpressured: true` flag ekle |
| Background | ≤ 20 | Normal kabul et |
| Background | > 20 | Sessizce atla (mesajı kuyruğa yazma, 200 döndür) |

### Akış Şeması

```
Backend isteği alır
        │
        ▼
Redis'ten kuyruk derinliğini oku (cache miss → 0 say)
        │
        ├─► Chat mı?
        │       └─► Circuit OPEN mu?  ──► EVET → 503 "AI asistanı şu an yoğun"
        │                               │
        │                               └─► HAYIR → Kuyruğa yaz → 202 Accepted
        │
        ├─► Authoring mı?
        │       └─► depth > 10?  ──► EVET → Kuyruğa yaz + {isBackpressured: true}
        │                          │
        │                          └─► HAYIR → Normal kuyruğa yaz
        │
        └─► Background mı?
                └─► depth > 20?  ──► EVET → Sessizce atla (mesaj yazılmaz)
                                   │
                                   └─► HAYIR → Normal kuyruğa yaz
```

---

## 6. Circuit Breaker ve Graceful Degradation

### Durum Makinesi

```
            3/5 başarısız
            (sliding window)
  CLOSED ──────────────────► OPEN
    ▲                          │
    │    yarı-açık test        │  30 saniye bekle
    │    başarılıysa           ▼
    └──────────────── HALF-OPEN
                     (tek test isteği)
```

| Durum | Açıklama |
|-------|----------|
| **CLOSED** | Normal çalışma, tüm istekler geçer |
| **OPEN** | Ollama arızalı; tüm istekler reddedilir veya fallback uygulanır |
| **HALF-OPEN** | 30s bekleyişten sonra tek bir test isteği gönderilir |

### Eşikler

- **Açılma koşulu:** Son 5 istekten 3'ü başarısız (`failure_threshold=3`, `window_size=5`)
- **Bekleme süresi:** 30 saniye (`recovery_timeout=30`)
- **Test isteği:** HALF-OPEN'da yalnızca 1 istek geçer; başarılıysa CLOSED'a döner

### Kuyruk Bazlı Davranış (Circuit OPEN iken)

| Kuyruk | Circuit OPEN Davranışı |
|--------|------------------------|
| `q.chat.requests` | Fallback yanıt: `"AI asistanı şu an yoğun, lütfen birkaç dakika sonra tekrar deneyin."` |
| `q.ai.authoring` | Mesajı `nack` et + kuyruğa geri al (`requeue=True`) |
| `q.ai.background` | Mesajı `nack` et + kuyruğa geri al (`requeue=True`) |

Chat için fallback yanıt tercih edilir çünkü kullanıcı aktif olarak bekliyordur; `requeue` yerine anında geri bildirim daha iyi kullanıcı deneyimi sağlar.

---

## 7. Retry Fırtınası Önleme

### Üstel Geri Çekilme (Exponential Backoff)

Başarısız bir mesaj yeniden kuyruğa alınmadan önce şu formülle hesaplanan süre kadar beklenir:

```
bekleme_süresi = min(2 × 4^(attempt - 1), 30)  [saniye]
```

| Deneme | Bekleme Süresi |
|--------|----------------|
| 1. deneme | 2 saniye (`2 × 4^0 = 2`) |
| 2. deneme | 8 saniye (`2 × 4^1 = 8`) |
| 3. deneme | 30 saniye (`2 × 4^2 = 32` → cap 30) |
| 4. deneme | 30 saniye (cap) |
| 5. deneme | 30 saniye (cap) |

### Retry Bütçesi (Retry Budget)

Aynı anda en fazla **3 retry mesajı** sistemde aktif olabilir. Bu değer Redis'te atomik sayaç olarak tutulur:

```
Redis key: retry:inflight:count
Operasyon: INCR (retry başlarken) / DECR (tamamlanınca veya DLQ'ya düşünce)
TTL: 300 saniye (sayaç sıkışmasına karşı güvenlik)
```

**Bütçe aşıldığında:** Yeni retry girişimi reddedilir; mesaj mevcut deneme sayısını koruyarak kuyruğa geri alınır ve bütçe azalınca yeniden denenir.

### Kuyruk Bazlı Maksimum Deneme Sayısı

| Kuyruk | Max Retry | Gerekçe |
|--------|-----------|---------|
| `q.chat.requests` | 2 | Kullanıcı 60s bekleyemez; hızlı DLQ'ya düş |
| `q.ai.authoring` | 3 | Admin işlemi, orta tolerans |
| `q.ai.background` | 5 | Arka plan, yüksek tolerans |

---

## 8. Queue Depth Signaling (Frontend)

Frontend, kuyruk durumunu iki kanaldan alır:

1. **API yanıtındaki flag'ler:** Authoring isteklerinde `isBackpressured` alanı
2. **SignalR üzerinden push:** Kuyruk derinliği değişikliklerinde anlık bildirim

### Chat İstemci Davranışı

```typescript
// Chat isteği gönderilir
// 60 saniye içinde yanıt gelmezse:
if (elapsedTime > 60_000) {
  showToast("AI asistanı şu an meşgul, lütfen tekrar deneyin.");
  abortRequest();
}

// Circuit state OPEN ise (HTTP 503):
if (response.status === 503) {
  showToast("AI servisi geçici olarak kullanılamıyor.");
  disableChatInputFor(30_000); // 30s devre bekleme süresi kadar
}
```

### Admin Panel Davranışı

```typescript
// Authoring isteği yanıtı
if (response.isBackpressured) {
  showBanner("AI kuyruğu yoğun, işleminiz alındı ancak gecikebilir.", "warning");
  // 10 saniye sonra banner otomatik kapanır
  setTimeout(() => clearBanner(), 10_000);
}
```

---

## 9. Redis Key'leri

| Key | İçerik | TTL | Kullanım |
|-----|--------|-----|---------|
| `queue:stats:q.chat.requests` | `{depth: int, updated_at: ISO}` | 30s | Backpressure kararı |
| `queue:stats:q.ai.authoring` | `{depth: int, updated_at: ISO}` | 30s | Backpressure kararı |
| `queue:stats:q.ai.background` | `{depth: int, updated_at: ISO}` | 30s | Backpressure kararı |
| `queue:stats:ollama:circuit_state` | `{state: "closed"\|"open"\|"half_open"}` | 30s | Circuit breaker durumu |
| `retry:inflight:count` | `int` (atomik sayaç) | 300s | Retry bütçesi takibi |

**Güncelleme Frekansı:** Kuyruk derinlik istatistikleri, consumer döngüsünün her iterasyonunda (yaklaşık her 5-10 saniyede bir) RabbitMQ Management API veya AMQP passiveQueueDeclare ile alınıp Redis'e yazılır. 30 saniyelik TTL, Redis erişilemez olsa bile son bilinen değerin kısa süre kullanılmasına izin verir.

---

## 10. Konfigürasyon Parametreleri

Tüm parametreler `app/core/config.py` dosyasında `Settings` sınıfı üzerinden yönetilir. Ortam değişkenleriyle geçersiz kılınabilir.

### Kuyruk Adları

```python
# Kuyruk adları
QUEUE_CHAT_REQUESTS: str = "q.chat.requests"
QUEUE_AI_AUTHORING: str = "q.ai.authoring"
QUEUE_AI_BACKGROUND: str = "q.ai.background"
QUEUE_AI_ANALYSIS_LEGACY: str = "q.ai.analysis"  # migration dönemi

# DLQ adları
DLQ_CHAT_REQUESTS: str = "dlq.chat.requests"
DLQ_AI_AUTHORING: str = "dlq.ai.authoring"
DLQ_AI_BACKGROUND: str = "dlq.ai.background"
```

### TTL ve Prefetch

```python
# TTL (milisaniye cinsinden — RabbitMQ formatı)
QUEUE_CHAT_TTL_MS: int = 60_000       # 60 saniye
QUEUE_AUTHORING_TTL_MS: int = 300_000  # 5 dakika
QUEUE_BACKGROUND_TTL_MS: int = 1_800_000  # 30 dakika

# Prefetch (consumer başına)
PREFETCH_CHAT: int = 2
PREFETCH_AUTHORING: int = 1
PREFETCH_BACKGROUND: int = 1
```

### Zamanlayıcı Slotları

```python
# PriorityScheduler eşzamanlılık sınırları
SCHEDULER_GLOBAL_SLOTS: int = 3   # Ollama toplam eşzamanlı istek
SCHEDULER_CHAT_SLOTS: int = 2     # Chat'e ayrılan maksimum slot
SCHEDULER_LOW_SLOTS: int = 1      # Background'a ayrılan slot
```

### Retry Parametreleri

```python
# Kuyruk bazlı maksimum deneme sayısı
MAX_RETRY_CHAT: int = 2
MAX_RETRY_AUTHORING: int = 3
MAX_RETRY_BACKGROUND: int = 5

# Backoff parametreleri
RETRY_BACKOFF_BASE: float = 2.0      # formül: base × multiplier^(attempt-1)
RETRY_BACKOFF_MULTIPLIER: float = 4.0
RETRY_BACKOFF_MAX_SECONDS: float = 30.0

# Retry bütçesi
RETRY_BUDGET_MAX_INFLIGHT: int = 3
RETRY_BUDGET_TTL_SECONDS: int = 300
```

### Circuit Breaker

```python
# Circuit breaker eşikleri
CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 3   # kaç başarısız
CIRCUIT_BREAKER_WINDOW_SIZE: int = 5          # kaç istek penceresi
CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = 30    # saniye (OPEN → HALF-OPEN)
```

### Backpressure Eşikleri

```python
# Kuyruk derinlik eşikleri (backend gateway)
BACKPRESSURE_AUTHORING_WARN_DEPTH: int = 10   # flag ekle
BACKPRESSURE_BACKGROUND_DROP_DEPTH: int = 20  # sessizce atla
```

---

## 11. Migration Planı

Mevcut `q.ai.analysis` kuyruğundan yeni topolojiye geçiş dört aşamada gerçekleştirilir. Her aşama bağımsız olarak deploy edilebilir ve geri alınabilir.

### Aşama 1: Yeni Kuyrukları Tanımla

**Hedef:** Yeni exchange, kuyruk ve DLQ yapısını RabbitMQ'ya ekle.
**Değişiklik:** Yalnızca AI Agent Service'in başlangıç kodu (`lifespan` veya `startup`).
**Etki:** Sıfır — yeni kuyruklar boş kalır, eski kuyruk çalışmaya devam eder.

```python
# Yapılacaklar:
# - blog.events exchange'ini direct olarak yeniden tanımla (idempotent)
# - q.chat.requests, q.ai.authoring, q.ai.background ve DLQ'larını declare et
# - Legacy q.ai.analysis kuyruğunu silme
```

### Aşama 2: Consumer Her İki Kuyruğu Dinle

**Hedef:** AI Agent Service hem eski hem yeni kuyruklardan mesaj tüketsin.
**Değişiklik:** `messaging/consumer.py` — her iki kuyruk için ayrı consumer başlat.
**Etki:** Düşük — geçiş süresince çift işlem riski, mesaj kimliğiyle idempotent işleme ile önlenir.

```python
# Yapılacaklar:
# - Legacy consumer → q.ai.analysis (eski)
# - Yeni consumer → q.chat.requests, q.ai.authoring, q.ai.background
# - Processor routing logic → her iki kaynak için aynı handler
```

### Aşama 3: Backend Yeni Kuyruklara Yayınlasın

**Hedef:** .NET backend artık yalnızca yeni routing key'lere yayın yapsın.
**Değişiklik:** `RabbitMqEventBus.cs` ve event sınıflarının routing key'leri.
**Etki:** Orta — bu deploy'dan sonra legacy kuyruk boşalmaya başlar.

```python
# Yapılacaklar:
# - Her event tipi için doğru routing key'i güncelle
# - Backpressure gateway entegrasyonunu ekle
# - Staging'de doğrula: yeni kuyruklarda mesajlar görünüyor mu?
```

### Aşama 4: Legacy Kuyruğu Kaldır

**Hedef:** `q.ai.analysis` consumer'ını kapat ve kuyruğu sil.
**Ön Koşul:** `q.ai.analysis` derinliği 0'a düşmüş olmalı, en az 24 saat gözlemlenmiş olmalı.
**Değişiklik:** Consumer kodundan legacy consumer başlatma kaldırılır.

```python
# Yapılacaklar:
# - Legacy consumer kodu sil
# - q.ai.analysis kuyruğunu RabbitMQ'dan sil (ya da otomatik silinmesine izin ver)
# - Config'den QUEUE_AI_ANALYSIS_LEGACY kaldır
```

### Geri Alma Prosedürü

Herhangi bir aşamada sorun yaşanırsa önceki aşamaya geri dönmek yeterlidir. Aşama 3 geri alınırsa (backend eski routing key'lere döner), Aşama 2 sayesinde legacy kuyruk yeniden tüketilmeye devam eder.

---

## 12. Troubleshooting

### Kuyruk Birikiyorsa

**Belirtiler:** RabbitMQ Management UI'da kuyruk derinliği artıyor, mesajlar işlenmiyor.

```bash
# 1. Ollama sağlık durumunu kontrol et
curl http://ollama:11434/api/tags

# 2. Circuit breaker durumunu kontrol et
redis-cli GET queue:stats:ollama:circuit_state
# Beklenen: {"state": "closed"} — "open" ise Ollama arızalı

# 3. Consumer'ın ayakta olduğunu doğrula
# RabbitMQ Management UI → Queues → q.ai.authoring → Consumers sekmesi
# Consumer bağlantısı yoksa AI Agent Service'i yeniden başlat

# 4. Prefetch'i kontrol et (tıkanma ihtimali)
# Prefetch=1 ile consumer bir mesajı acknowledge etmeden yenisini almaz
# Ollama çok yavaşsa prefetch sorun değil, Ollama'yı incele
```

### Retry Fırtınası Yaşanıyorsa

**Belirtiler:** Ollama CPU/GPU %100, aynı mesajlar tekrar tekrar işleniyor, backoff çalışmıyor gibi görünüyor.

```bash
# 1. Retry inflight sayacını kontrol et
redis-cli GET retry:inflight:count
# Beklenen: 0-3 arası — 3'teyse bütçe dolu, yeni retry'lar beklemeye alınmış

# 2. Sayaç sıkışmışsa (örn. servis çöküşüyle DECR yapılamamış) sıfırla
redis-cli SET retry:inflight:count 0

# 3. Backoff değerlerini artır (geçici önlem)
# Config'de RETRY_BACKOFF_MULTIPLIER değerini 4.0'dan 8.0'a çıkar
# Servis yeniden başlatılmalı

# 4. DLQ'ları incele — hangi mesajlar sürekli başarısız oluyor?
# RabbitMQ Management UI → dlq.ai.authoring → Get Messages
```

### Chat Yanıt Gelmiyor

**Belirtiler:** Kullanıcı chat mesajı gönderiyor, yanıt gelmiyor veya çok geç geliyor.

```bash
# 1. TTL kontrolü — mesaj 60 saniye içinde işlenemiyor mu?
# RabbitMQ Management UI → q.chat.requests → Messages sekmesi
# Mesajlar DLQ'ya mı düşüyor? → dlq.chat.requests'i kontrol et

# 2. Circuit breaker açık mı?
redis-cli GET queue:stats:ollama:circuit_state
# "open" ise 30 saniye bekle veya manuel CLOSED'a al:
redis-cli SET queue:stats:ollama:circuit_state '{"state":"closed"}'

# 3. Consumer loglarını incele
docker logs ai-agent-service --tail 100 | grep "chat"
# Hata mesajı var mı? Timeout mu alıyor?

# 4. Prefetch ve slot kontrolü
# PriorityScheduler global_semaphore 3 slot dolu mu?
# Authoring/background görevleri slotları meşgul ediyor olabilir
# Çözüm: SCHEDULER_CHAT_SLOTS geçici olarak 3'e çıkar ve test et

# 5. SignalR bağlantısı kopmuş olabilir (frontend tarafı)
# Browser Console → WebSocket bağlantı hatası var mı?
# Frontend'de SignalR'ı yeniden bağlat
```

### Genel Sağlık Kontrol Komutu

```bash
# Tüm kuyruk derinliklerini bir anda gör
redis-cli MGET \
  queue:stats:q.chat.requests \
  queue:stats:q.ai.authoring \
  queue:stats:q.ai.background \
  queue:stats:ollama:circuit_state \
  retry:inflight:count
```

---

## Ek: Bileşen Sorumluluk Özeti

| Bileşen | Dosya | Sorumluluk |
|---------|-------|------------|
| Kuyruk tanımları | `app/infrastructure/messaging/rabbitmq_adapter.py` | Exchange, kuyruk, DLQ declare |
| Consumer başlatma | `app/messaging/consumer.py` | Her kuyruk için channel açma, prefetch ayarı |
| Mesaj yönlendirme | `app/messaging/processor.py` | Routing key → handler eşleştirme |
| Öncelik zamanlayıcısı | `app/services/message_processor_service.py` | Semafor yönetimi, öncelik mantığı |
| Circuit breaker | `app/infrastructure/llm/ollama_adapter.py` | Hata sayımı, durum geçişleri |
| Backpressure gateway | `app/api/v1/endpoints/chat.py` + `analysis.py` | Kuyruk derinliği okuma, flag ekleme |
| Redis istatistik yazma | `app/core/cache.py` | Kuyruk derinliği Redis'e yazma |
| Retry bütçesi | `app/services/message_processor_service.py` | `retry:inflight:count` yönetimi |
| Konfigürasyon | `app/core/config.py` | Tüm parametrelerin merkezi yönetimi |

---

*Bu belge `2026-03-18` tarihinde oluşturulmuştur. Topoloji veya parametre değişikliklerinde güncellenmelidir.*
