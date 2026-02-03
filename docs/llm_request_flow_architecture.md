# LLM Sohbet İstek Akış Mimarisi

## Genel Bakış

Bu belge, kullanıcıların blog makaleleri hakkında sorular sorabileceği LLM destekli sohbet özelliğinin uçtan uca mimarisini açıklar. Sistem, mesajlaşma aracılığı olarak RabbitMQ ve backend ile frontend arasındaki gerçek zamanlı iletişim için SignalR kullanan olay tabanlı, asenkron bir mimari uygular.

Sohbet sistemi aşağıdaki özellikleri destekler:
- **RAG (Retrieval-Augmented Generation)** - Makale içeriğine dayalı bağlam fark eden yanıtlar
- **Web Arama Entegrasyonu** - Geliştirilmiş yanıtlar için isteğe bağlı web araması
- **Sohbet Geçmişi** - Bağlam korumalı çok dönüşlü sohbetler
- **Gerçek Zamanlı Yanıtlar** - AI yanıtlarının anlık teslimatı için SignalR

## Mimari Bileşenleri

### 1. Frontend (blogapp-web)

**Konum:** `/mnt/d/MrBekoXBlogApp/src/blogapp-web`

**Önemli Dosyalar:**
- `src/hooks/use-article-chat.ts` - Sohbet işlevselliği için React hook
- `src/stores/chat-store.ts` - Sohbet için Zustand durum yönetimi
- `src/lib/api.ts` - HTTP istekleri için API istemcisi

**Sorumluluklar:**
- Sohbet UI durumunu yönetme (mesajlar, yükleme durumu, oturum ID'si)
- Gerçek zamanlı güncellemeler için SignalR bağlantısı kurma
- HTTP POST yoluyla sohbet mesajlarını gönderme
- SignalR yoluyla AI yanıtlarını alma ve görüntüleme
- Sohbet geçmişini yönetme

**Teknoloji Yığını:**
- Next.js 14 (App Router)
- Durum yönetimi için Zustand
- WebSocket bağlantısı için @microsoft/signalr
- TypeScript

### 2. Backend API (BlogApp.Server.Api)

**Konum:** `/mnt/d/MrBekoXBlogApp/src/BlogApp.Server/BlogApp.Server.Api`

**Önemli Dosyalar:**
- `Endpoints/ChatEndpoints.cs` - Sohbet istekleri için HTTP endpoint
- `Messaging/ChatResponseHandler.cs` - AI yanıtları için RabbitMQ tüketici
- `Hubs/CacheInvalidationHub.cs` - Gerçek zamanlı yayınlar için SignalR hub

**Sorumluluklar:**
- HTTP POST yoluyla sohbet isteklerini alma
- Makale varlığını doğrulama
- Oturum ID'leri ve korelasyon ID'leri oluşturma
- RabbitMQ'ya sohbet istek olaylarını yayınlama
- RabbitMQ'dan sohbet yanıt olaylarını tüketme
- SignalR yoluyla istemcilere yanıtları yayınlama

**Teknoloji Yığını:**
- ASP.NET Core 8.0
- WebSockets için SignalR
- Mesajlaşma için RabbitMQ.Client

### 3. Mesajlaşma Aracısı (RabbitMQ)

**Topoloji:**
- **Exchange:** `blog.events` (Direct tipi, dayanıklı)
- **Queue:** `q.ai.analysis` (Quorum tipi, dayanıklı)
- **Dead Letter Exchange:** `dlx.blog`
- **Dead Letter Queue:** `dlq.ai.analysis`

**Routing Keys:**
- `chat.message.requested` - Backend → AI Agent
- `chat.message.completed` - AI Agent → Backend

**Özellikler:**
- Kalıcı mesaj teslimatı
- Başarısız mesajlar için dead letter kuyruğu
- Dayanıklılık için quorum kuyruğu
- İstek takibi için korelasyon ID'leri

### 4. AI Agent Servisi (Python)

**Konum:** `/mnt/d/MrBekoXBlogApp/src/services/ai-agent-service`

**Önemli Dosyalar:**
- `app/messaging/consumer.py` - RabbitMQ tüketici
- `app/messaging/processor.py` - Mesaj işleme mantığı
- `app/agent/rag_chat_handler.py` - RAG implementasyonu
- `app/rag/retriever.py` - Vektör arama retrieve edici
- `app/tools/web_search.py` - Web arama entegrasyonu

**Sorumluluklar:**
- RabbitMQ'dan sohbet istek mesajlarını tüketme
- RAG kullanarak ilgili makale içeriğini retrieve etme
- Etkinleştirilirse web araması yapma (hibrit arama)
- LLM kullanarak AI yanıtları oluşturma
- RabbitMQ'ya yanıt olaylarını geri yayınlama
- Idempotency ve distributed kilitleme işleme

**Teknoloji Yığını:**
- Python 3.11+
- Async RabbitMQ için aio-pika
- LLM için OpenAI API
- Vektör depolama için ChromaDB
- Önbellekleme ve kilitleme için Redis

### 5. SignalR Hub (Gerçek Zamanlı İletişim)

**Endpoint:** `/hubs/cache`

**Amaç:**
- İstemcilerle kalıcı WebSocket bağlantıları sürdürme
- Tüm bağlı istemcilere sohbet yanıtlarını yayınlama
- Oturum tabanlı filtreleme desteği
- Otomatik yeniden bağlanma işleme

**Olaylar:**
- `ChatMessageReceived` - AI yanıtı geldiğinde yayınlanır

## İstek Akışı

### Adım Adım Akış

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│  Frontend   │         │   Backend    │         │  RabbitMQ   │
│ (Next.js)   │         │  (.NET API)  │         │  Message Bus│
└──────┬──────┘         └──────┬───────┘         └──────┬──────┘
       │                       │                         │
       │ 1. Kullanıcı mesaj gönderir │                         │
       │──────────────────────>│                         │
       │    POST /api/v1/chat/message                    │
       │                       │                         │
       │                       │ 2. Doğrula & Yayınla   │
       │                       │────────────────────────>│
       │                       │   chat.message.requested │
       │                       │                         │
       │ 3. Return 202 Kabul Edildi│                         │
       │<──────────────────────│                         │
       │    { sessionId }      │                         │
       │                       │                         │
       │ 4. SignalR Bağlı     │                         │
       │<──────────────────────�┘                         │
       │    Yanıt bekliyor                         │
       │                       │                         │
┌──────┴──────┐         ┌──────┴───────┐         ┌──────┴──────┐
│  Frontend   │         │   Backend    │         │  RabbitMQ   │
│ (Next.js)   │         │  (.NET API)  │         │  Message Bus│
└─────────────┘         └──────────────┘         └──────┬──────┘
                                                      │
                                                      │ 5. AI Agent tüketir
                                                      │
┌─────────────┐         ┌──────────────┐         ┌──────┴──────┐
│  RabbitMQ   │         │  AI Agent    │         │   ChromaDB  │
│  Message Bus│         │   (Python)   │         │  Vector Store│
└──────┬──────┘         └──────┬───────┘         └──────┬──────┘
       │                       │                         │
       │<──────────────────────�│                         │
       │   Mesaj tüketilir      │                         │
       │                       │                         │
       │                       │ 6. RAG Retrieval        │
       │                       │------------------------>│
       │                       │   Vektör Arama         │
       │                       │                         │
       │                       │ 7. Web Arama (opsiyonel)│
       │                       │────────────────────────>│
       │                       │   Harici API          │
       │                       │                         │
       │                       │ 8. AI Yanıt Oluştur   │
       │                       │    (LLM Çağrısı)      │
       │                       │                         │
       │ 9. Yanıt Yayınla     │                         │
       │<──────────────────────│                         │
       │   chat.message.completed                         │
       │                       │                         │
┌──────┴──────┐         ┌──────┴───────┐         ┌──────┴──────┐
│  RabbitMQ   │         │  AI Agent    │         │   External  │
│  Message Bus│         │   (Python)   │         │   Web API   │
└──────┬──────┘         └──────────────┘         └─────────────┘
       │
       │ 10. Backend tüketir
       │
┌──────┴──────┐         ┌──────────────┐
│  Backend    │         │   SignalR    │
│  (.NET API) │         │     Hub      │
└──────┬──────┘         └──────┬───────┘
       │                       │
       │ 11. SignalR ile yayınla
       │──────────────────────>│
       │    ChatMessageReceived│
       │                       │
       │                       │ 12. İstemcilere yayınla
       │                       │──────────────────────>┌─────────────┐
       │                       │                       │  Frontend   │
       │                       │                       │ (Next.js)   │
       │                       │                       │             │
       │                       │                       │ 13. Görüntüle │
       │                       │                       │    Yanıt    │
       │                       │                       │<────────────┘
       │                       │                       │
┌──────┴──────┐         ┌──────┴───────┐         ┌──────┴──────┐
│  Backend    │         │   SignalR    │         │  Frontend   │
│  (.NET API) │         │     Hub      │         │ (Next.js)   │
└─────────────┘         └──────────────┘         └─────────────┘
```

### Detaylı Adımlar

#### Adım 1: Kullanıcı Mesaj Gönderir
**Bileşen:** Frontend (React Hook)
**Dosya:** `src/hooks/use-article-chat.ts`

```typescript
// Kullanıcı mesaj gönderme işlemini tetikler
await sendMessage("Bu makale hakkında ne söylersin?", false);
```

**Eylem:** Sohbet durumu kullanıcı mesajıyla güncellenir, yükleme durumu 'analyzing' olarak ayarlanır

#### Adım 2: Frontend Backend API'yi Çağırır
**Bileşen:** Chat Store
**Dosya:** `src/stores/chat-store.ts`

```typescript
const response = await chatApi.sendMessage({
  postId: "123e4567-e89b-12d3-a456-426614174000",
  message: "Bu makale hakkında ne söylersin?",
  sessionId: sessionId || undefined,
  conversationHistory: [...], // Önceki mesajlar
  language: 'tr',
  enableWebSearch: false
});
```

**HTTP İsteği:**
```
POST /api/v1/chat/message
Content-Type: application/json

{
  "postId": "123e4567-e89b-12d3-a456-426614174000",
  "message": "Bu makale hakkında ne söylersin?",
  "sessionId": null,
  "conversationHistory": [],
  "language": "tr",
  "enableWebSearch": false
}
```

#### Adım 3: Backend Doğrular ve Olay Yayar
**Bileşen:** Chat Endpoint
**Dosya:** `src/BlogApp.Server/BlogApp.Server.Api/Endpoints/ChatEndpoints.cs`

```csharp
// 1. Makale varlığını doğrula
var post = await unitOfWork.PostsRead.GetByIdAsync(request.PostId);

// 2. Oturum ID oluştur
var sessionId = string.IsNullOrEmpty(request.SessionId)
    ? Guid.NewGuid().ToString()
    : request.SessionId;

// 3. Korelasyon ID oluştur
var correlationId = Guid.NewGuid().ToString();

// 4. Olay oluştur
var chatEvent = new ChatRequestedEvent
{
    CorrelationId = correlationId,
    Payload = new ChatRequestPayload
    {
        SessionId = sessionId,
        PostId = request.PostId,
        ArticleTitle = post.Title,
        ArticleContent = post.Content,
        UserMessage = request.Message,
        ConversationHistory = history,
        Language = request.Language ?? "tr",
        EnableWebSearch = request.EnableWebSearch
    }
};

// 5. RabbitMQ'ya yayınla
await eventBus.PublishAsync(
    chatEvent,
    MessagingConstants.RoutingKeys.ChatMessageRequested,
    cancellationToken);
```

**Yayınlanan RabbitMQ Mesajı:**
```json
{
  "messageId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "correlationId": "f6e5d4c3-b2a1-9087-6543-210987654321",
  "timestamp": "2026-01-25T10:30:00Z",
  "eventType": "chat.message.requested",
  "payload": {
    "sessionId": "session-123",
    "postId": "123e4567-e89b-12d3-a456-426614174000",
    "articleTitle": "Mikroservislere Giriş",
    "articleContent": "...",
    "userMessage": "Bu makale hakkında ne söylersin?",
    "conversationHistory": [],
    "language": "tr",
    "enableWebSearch": false
  }
}
```

**Routing Key:** `chat.message.requested`
**Exchange:** `blog.events`

#### Adım 4: Backend 202 Kabul Edildi Döner
**HTTP Yanıtı:**
```json
{
  "correlationId": "f6e5d4c3-b2a1-9087-6543-210987654321",
  "sessionId": "session-123",
  "message": "Sohbet isteği kabul edildi"
}
```

Durum Kodu: `202 Accepted`

#### Adım 5: Frontend SignalR Yanıtını Bekler
**Bileşen:** SignalR Bağlantısı
**Dosya:** `src/hooks/use-article-chat.ts`

Frontend zaten `/hubs/cache` adresindeki SignalR hub'ına bağlı ve `ChatMessageReceived` olayını dinliyor.

#### Adım 6: AI Agent Mesajı Tüketir
**Bileşen:** RabbitMQ Consumer
**Dosya:** `src/services/ai-agent-service/app/messaging/consumer.py`

```python
# Consumer q.ai.analysis kuyruğunu dinliyor
# chat.message.requested routing key'ine bağlı

async def _handle_message(self, message: aio_pika.IncomingMessage):
    # Mesajı ayrıştır
    success, reason = await self._processor.process_message(message.body)

    if success:
        await message.ack()  # Başarılı işleme bildirimi
```

#### Adım 7: AI Agent İsteği İşler
**Bileşen:** Message Processor
**Dosya:** `src/services/ai-agent-service/app/messaging/processor.py`

```python
async def _process_chat(self, message: ChatRequestMessage) -> dict:
    payload = message.payload
    post_id = payload.postId
    user_message = payload.userMessage
    language = payload.language
    enable_web_search = payload.enableWebSearch

    # Geçmişi ChatMessage nesnelerine dönüştür
    history = [
        ChatMessage(role=item.role, content=item.content)
        for item in payload.conversationHistory
    ]

    # Dal 1: Web Arama Etkin (Hibrit Arama)
    if enable_web_search:
        # 1. LLM kullanarak akıllı arama sorgusu oluştur
        smart_query = await rag_chat_handler.generate_search_query(
            article_title=payload.articleTitle,
            user_question=user_message,
            article_content=payload.articleContent,
            language=language
        )

        # 2. Paralel çalıştırma: Web Arama + RAG
        rag_task = retriever.retrieve_with_context(
            query=user_message,
            post_id=post_id,
            k=5
        )

        web_task = web_search_tool.search(
            query=smart_query,
            max_results=10,
            region="tr-tr" if language == "tr" else "us-en"
        )

        # 3. İkisini de bekle
        retrieval_result, search_results = await asyncio.gather(rag_task, web_task)

        # 4. Hibrit bağlamla yanıt oluştur
        if search_results.has_results:
            response = await rag_chat_handler.chat_with_web_search(
                post_id=post_id,
                user_message=user_message,
                article_title=payload.articleTitle,
                web_search_results=[r.to_dict() for r in search_results.results],
                rag_context=retrieval_result.context,
                language=language
            )

            return {
                "response": response.response,
                "isWebSearchResult": True,
                "sources": [r.to_dict() for r in search_results.results]
            }

    # Dal 2: Saf RAG (Web Arama Yok)
    response = await rag_chat_handler.chat(
        post_id=post_id,
        user_message=user_message,
        conversation_history=history,
        language=language
    )

    return {
        "response": response.response,
        "isWebSearchResult": False,
        "sources": None
    }
```

**RAG Retrieval Süreci:**
1. İlgili makale parçaları için vektör deposunda sorgula
2. Top-k parçalarını retrieve et (varsayılan k=5)
3. Retrieve edilen parçalardan bağlam oluştur
4. Bağlam + kullanıcı sorusuyla LLM yanıtı oluştur

**Web Arama Süreci (etkinse):**
1. LLM kullanarak optimize edilmiş arama sorgusu oluştur
2. Harici web API'sinde ara (DuckDuckGo)
3. İlk 10 sonucu retrieve et
4. Web arama sonuçlarını RAG bağlamıyla birleştir
5. Geliştirilmiş LLM yanıtı oluştur

#### Adım 8: AI Agent Yanıt Yayar
**Bileşen:** Message Processor
**Dosya:** `src/services/ai-agent-service/app/messaging/processor.py`

```python
async def _save_chat_result(self, session_id: str, result: dict, correlation_id: str) -> bool:
    message = {
        "messageId": str(uuid.uuid4()),
        "correlationId": correlation_id,
        "timestamp": datetime.utcnow().isoformat(),
        "eventType": "chat.message.completed",
        "payload": {
            "sessionId": session_id,
            "response": result.get("response", ""),
            "isWebSearchResult": result.get("isWebSearchResult", False),
            "sources": result.get("sources")
        }
    }

    await self._exchange.publish(
        aio_pika.Message(
            body=json.dumps(message).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=message["messageId"],
            correlation_id=message["correlationId"],
        ),
        routing_key=CHAT_RESPONSE_ROUTING_KEY,  # "chat.message.completed"
    )
```

**Yayınlanan RabbitMQ Mesajı:**
```json
{
  "messageId": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "correlationId": "f6e5d4c3-b2a1-9087-6543-210987654321",
  "timestamp": "2026-01-25T10:30:05Z",
  "eventType": "chat.message.completed",
  "payload": {
    "sessionId": "session-123",
    "response": "Bu makale mikroservis mimarisinin temellerini tartışıyor...",
    "isWebSearchResult": false,
    "sources": null
  }
}
```

**Routing Key:** `chat.message.completed`
**Exchange:** `blog.events`

#### Adım 9: Backend Yanıt Olayını Tüketir
**Bileşen:** Chat Response Handler
**Dosya:** `src/BlogApp.Server/BlogApp.Server.Api/Messaging/ChatResponseHandler.cs`

```csharp
public class ChatResponseHandler : IEventHandler<ChatResponseEvent>
{
    private readonly IHubContext<CacheInvalidationHub> _hubContext;

    public async Task HandleAsync(ChatResponseEvent @event, CancellationToken cancellationToken)
    {
        var sessionId = @event.Payload.SessionId;
        var correlationId = @event.CorrelationId;

        // Yanıt verisini hazırla
        var responseData = new
        {
            SessionId = sessionId,
            CorrelationId = correlationId,
            Response = @event.Payload.Response,
            IsWebSearchResult = @event.Payload.IsWebSearchResult,
            Sources = @event.Payload.Sources?.Select(s => new
            {
                s.Title,
                s.Url,
                s.Snippet
            }),
            Timestamp = DateTime.UtcNow
        };

        // SignalR yoluyla tüm bağlı istemcilere yayınla
        await _hubContext.Clients.All.SendAsync(
            "ChatMessageReceived",
            responseData,
            cancellationToken);
    }
}
```

#### Adım 10: SignalR Frontend'e Yayar
**SignalR Olayı:**
```json
{
  "sessionId": "session-123",
  "correlationId": "f6e5d4c3-b2a1-9087-6543-210987654321",
  "response": "Bu makale mikroservis mimarisinin temellerini tartışıyor...",
  "isWebSearchResult": false,
  "sources": null,
  "timestamp": "2026-01-25T10:30:05Z"
}
```

**Olay Adı:** `ChatMessageReceived`
**Hub:** `/hubs/cache`

#### Adım 11: Frontend Yanıtı Alır ve Görüntüler
**Bileşen:** SignalR Handler
**Dosya:** `src/hooks/use-article-chat.ts`

```typescript
connection.on('ChatMessageReceived', (event: Record<string, unknown>) => {
  const eventSessionId = event.sessionId || event.SessionId;
  const eventResponse = event.response || event.Response;
  const eventIsWebSearch = event.isWebSearchResult ?? event.IsWebSearchResult ?? false;
  const eventSources = event.sources || event.Sources;

  // Bu mesajın bizim oturumumuz için olup olmadığını kontrol et
  if (eventSessionId === currentSessionId || !currentSessionId) {
    // Store'a assistant mesajı ekle
    addAssistantMessageRef.current?.(
      eventResponse || '',
      eventIsWebSearch,
      eventSources
    );

    // Yükleme durumu temizlendi, mesaj görüntülendi
  }
});
```

**Durum Güncellemesi:** `chat-store.ts`
```typescript
addAssistantMessage: (content, isWebSearchResult = false, sources) => {
  const assistantMessage: ChatMessage = {
    id: crypto.randomUUID(),
    role: 'assistant',
    content,
    isWebSearchResult,
    sources,
    timestamp: new Date(),
  };

  set((state) => ({
    messages: [...state.messages, assistantMessage],
    isLoading: false,  // Yükleme tamamlandı
    loadingState: 'idle',
  }));
}
```

## Temel Veri Yapıları

### Chat Request DTO
**Dosya:** `src/BlogApp.Server/BlogApp.Server.Api/Endpoints/ChatEndpoints.cs`

```csharp
public record ChatMessageRequest
{
    public Guid PostId { get; init; }
    public string Message { get; init; }
    public string? SessionId { get; init; }
    public List<ChatHistoryItemRequest>? ConversationHistory { get; init; }
    public string? Language { get; init; }
    public bool EnableWebSearch { get; init; }
}

public record ChatHistoryItemRequest
{
    public string Role { get; init; }  // "user" veya "assistant"
    public string Content { get; init; }
}
```

### ChatRequestedEvent
**Dosya:** `src/BlogApp.Server/BlogApp.Server.Application/Common/Events/ChatEvents.cs`

```csharp
public record ChatRequestedEvent : IntegrationEvent
{
    public override string EventType => "chat.message.requested";
    public ChatRequestPayload Payload { get; init; }
}

public record ChatRequestPayload
{
    public string SessionId { get; init; }
    public Guid PostId { get; init; }
    public string ArticleTitle { get; init; }
    public string ArticleContent { get; init; }
    public string UserMessage { get; init; }
    public List<ChatHistoryItem> ConversationHistory { get; init; }
    public string Language { get; init; }
    public bool EnableWebSearch { get; init; }
}

public record ChatHistoryItem
{
    public string Role { get; init; }
    public string Content { get; init; }
}
```

### ChatResponseEvent
**Dosya:** `src/BlogApp.Server/BlogApp.Server.Application/Common/Events/ChatEvents.cs`

```csharp
public record ChatResponseEvent : IntegrationEvent
{
    public override string EventType => "chat.message.completed";
    public ChatResponsePayload Payload { get; init; }
}

public record ChatResponsePayload
{
    public string SessionId { get; init; }
    public string Response { get; init; }
    public bool IsWebSearchResult { get; init; }
    public List<WebSearchSource>? Sources { get; init; }
}

public record WebSearchSource
{
    public string Title { get; init; }
    public string Url { get; init; }
    public string Snippet { get; init; }
}
```

### Frontend Chat Message
**Dosya:** `src/blogapp-web/src/types/index.ts`

```typescript
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  isWebSearchResult?: boolean;
  sources?: WebSearchSource[];
}

interface WebSearchSource {
  title: string;
  url: string;
  snippet: string;
}
```

## Teknik Detaylar

### RabbitMQ Topolojisi

**Exchange Yapılandırması:**
- **Ad:** `blog.events`
- **Tip:** Direct
- **Dayanıklı:** Evet
- **Otomatik silme:** Hayır

**Queue Yapılandırması:**
- **Ad:** `q.ai.analysis`
- **Tip:** Quorum (dayanıklılık ve tutarlılık için)
- **Dayanıklı:** Evet
- **DLX:** `dlx.blog`
- **Dead Letter Routing Key:** `#`

**Bağlantılar:**
| Queue | Exchange | Routing Key |
|-------|----------|-------------|
| `q.ai.analysis` | `blog.events` | `chat.message.requested` |
| `q.ai.analysis` | `blog.events` | `article.created` |
| `q.ai.analysis` | `blog.events` | `article.published` |
| `q.ai.analysis` | `blog.events` | `article.updated` |
| `q.chat.responses` | `blog.events` | `chat.message.completed` |

**Dead Letter Queue:**
- **DLX Exchange:** `dlx.blog`
- **DLQ Adı:** `dlq.ai.analysis`
- **Amaç:** Başarısız mesajları analiz için sakla

### Olay Türleri

**Sohbet Olayları:**
| Olay Tipi | Yön | Routing Key | Yayıncı | Tüketici |
|------------|-----------|-------------|-----------|----------|
| `chat.message.requested` | Backend → AI Agent | `chat.message.requested` | Backend API | AI Agent |
| `chat.message.completed` | AI Agent → Backend | `chat.message.completed` | AI Agent | Backend |

**Makale Olayları (ayrıca AI Agent tarafından tüketilir):**
| Olay Tipi | Yön | Routing Key |
|------------|-----------|-------------|
| `article.created` | Backend → AI Agent | `article.created` |
| `article.published` | Backend → AI Agent | `article.published` |
| `article.updated` | Backend → AI Agent | `article.updated` |

### SignalR Hub Yapılandırması

**Hub Endpoint:** `/hubs/cache`

**Hub Metotları:**
- `SubscribeToGroup(string groupName)` - Bir cache grubuna katıl
- `UnsubscribeFromGroup(string groupName)` - Bir cache grubundan ayrıl

**İstemci Olayları:**
- `ChatMessageReceived` - AI sohbet yanıtını al
- `AIAnalysisCompleted` - AI analiz sonuçlarını al

**Bağlantı Seçenekleri:**
```typescript
new signalR.HubConnectionBuilder()
  .withUrl(`${BASE_URL}/hubs/cache`, {
    withCredentials: true,  // Auth çerezlerini gönder
  })
  .withAutomaticReconnect()  // Bağlantı kesilirse otomatik yeniden bağlan
  .configureLogging(signalR.LogLevel.Debug)
  .build();
```

### Mesaj Akışı Özellikleri

**Korelasyon ID:**
- İstek alındığında backend tarafından oluşturulur
- Tüm akıştan geçer (istek → işleme → yanıt)
- Hizmetler arası istek yaşam döngüsünü takip etmek için kullanılır
    * Her adımda hata ayıklama için günlüğe kaydedilir

**Oturum ID:**
- Sohbetteki ilk mesajda oluşturulur
- Çok dönüşlü sohbette mesajları gruplamak için kullanılır
- Birden fazla istek boyunca kalır
    * Frontend sonraki isteklere dahil eder

**Mesaj ID:**
- Her mesaj için benzersiz tanımlayıcı
    * AI Agent'da idempotency kontrolleri için kullanılır
    * Yinelenen işlemeyi önler

### Hata İşleme

**Frontend:**
- Ağ hataları toast bildirimlerini tetikler
    * SignalR kesintisi yeniden bağlanma girişimlerini tetikler
    * Başarısız mesajlar UI'da hata göstergesiyle kalır

**Backend:**
- RabbitMQ yayın başarısızlıkları günlüğe kaydedilir (fırlatmaz)
    * Eksik gönderiler 404 döner
    * Doğrulama hataları 400 döner

**AI Agent:**
- Hatalı biçimlendirilmiş mesajlar reddedilir (NACK, yeniden kuyruklanmaz)
    * Kurtarılamaz HTTP hataları (404, 400) DLQ'ya gönderilir
    * Kurtarılabilir hatalar 5 kez yeniden kuyruklanır
    * Dağıtılmış kilitleme eşzamanlı işlemeyi önler

**Dead Letter Queue:**
- Başarısız mesajlar analiz için saklanır
    * İncelenebilir ve manuel olarak yeniden尝试 edilebilir
    * Sonsuz yeniden deneme döngülerini önler

### Performans Hususları

**Async İşleme:**
- Backend hemen döner (202 Kabul Edildi)
    * AI yanıtları için engelleyici beklemeler yok
    * Frontend duyarlı kalır

**RabbitMQ QoS:**
- Prefetch sayısı: 1
    * Tüketici aşırı yüklenmesini önler
    * Backpressure kontrolünü sağlar

**Paralel Çalıştırma (Web Arama + RAG):**
```python
# Web aramasını ve RAG retrieval'ini paralel çalıştır
rag_task = retriever.retrieve_with_context(...)
web_task = web_search_tool.search(...)

# İkisinin de tamamlanmasını bekle
retrieval_result, search_results = await asyncio.gather(rag_task, web_task)
```

**Idempotency:**
- Redis önbelleği işlenen mesaj ID'lerini takip eder
    * Dağıtılmış kilitler yinelenen işlemeyi önler
    * Yinelenen mesajların zarif şekilde ele alınması

### Güvenlik

**Kimlik Doğrulama:**
- Frontend HTTP isteğiyle auth çerezleri gönderir
    * SignalR bağlantısı `withCredentials: true` kullanır
    * Backend kullanıcı oturumunu doğrular

**Yetkilendirme:**
- İşlemeden önce makale erişimi doğrulanır
    * Kullanıcı sadece erişilebilir gönderiler hakkında sohbet edebilir

**CORS:**
- SignalR hub izin verilen kaynaklar için yapılandırıldı
    * HTTP endpoint'lerinde CORS politikaları var

### Yapılandırma

**Ortam Değişkenleri (Backend):**
```bash
RABBITMQ_ENABLED=true
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USERNAME=guest
RABBITMQ_PASSWORD=guest
SIGNALR_HUB_ENDPOINT=/hubs/cache
```

**Ortam Değişkenleri (AI Agent):**
```bash
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
OPENAI_API_KEY=sk-...
REDIS_URL=redis://localhost:6379/0
CHROMADB_HOST=localhost
CHROMADB_PORT=8000
```

**Ortam Değişkenleri (Frontend):**
```bash
NEXT_PUBLIC_API_URL=http://localhost:5116/api/v1
```

## Diyagramlar

### Mermaid Sekans Diyagramı

```mermaid
sequenceDiagram
    participant User as Kullanıcı
    participant Frontend as Next.js Frontend
    participant API as .NET Backend API
    participant RabbitMQ as RabbitMQ
    participant AI as AI Agent (Python)
    participant VectorDB as ChromaDB
    participant WebAPI as Web Arama API
    participant SignalR as SignalR Hub

    User->>Frontend: Mesaj gönder
    Frontend->>Frontend: Durumu güncelle (yükleniyor)
    Frontend->>API: POST /api/v1/chat/message

    API->>API: Gönderi varlığını doğrula
    API->>API: Oturum & korelasyon ID'leri oluştur
    API->>RabbitMQ: chat.message.requested yayınla
    Note over RabbitMQ: Exchange: blog.events<br/>Routing Key: chat.message.requested

    API-->>Frontend: 202 Kabul Edildi
    Note over Frontend: sessionId: "session-123"

    RabbitMQ->>AI: Mesajı tüket
    Note over AI: Queue: q.ai.analysis

    alt Web Arama Etkin
        AI->>AI: Akıllı sorgu oluştur
        par Paralel Çalıştırma
            AI->>VectorDB: Vektör arama (RAG)
            VectorDB-->>AI: Retrieve edilen parçalar
        and
            AI->>WebAPI: Web araması
            WebAPI-->>AI: Arama sonuçları
        end
        AI->>AI: Hibrit bağlamla yanıt oluştur
    else Web Arama Devre Dışı
        AI->>VectorDB: Vektör arama (RAG)
        VectorDB-->>AI: Retrieve edilen parçalar
        AI->>AI: RAG bağlamıyla yanıt oluştur
    end

    AI->>RabbitMQ: chat.message.completed yayınla
    Note over RabbitMQ: Exchange: blog.events<br/>Routing Key: chat.message.completed

    RabbitMQ->>API: Mesajı tüket
    API->>SignalR: ChatMessageReceived yayınla
    SignalR->>Frontend: Olayı it
    Frontend->>Frontend: Durumu güncelle (yanıtı görüntüle)
    Frontend->>User: AI yanıtını görüntüle
```

### Mimari Diyagram

```mermaid
graph TB
    subgraph "Frontend Katmanı"
        UI[Sohbet UI Bileşeni]
        Hook[useArticleChat Hook]
        Store[Sohbet Store]
        SignalRClient[SignalR İstemcisi]
    end

    subgraph "API Katmanı"
        Endpoint[Sohbet Endpoint]
        EventBus[RabbitMQ Event Bus]
        Handler[Sohbet Yanıt İşleyici]
        SignalRHub[Cache Invalidation Hub]
    end

    subgraph "Mesaj Aracısı"
        Exchange[blog.events Exchange]
        Queue[q.ai.analysis Queue]
        DLQ[Dead Letter Queue]
    end

    subgraph "AI Servis Katmanı"
        Consumer[RabbitMQ Tüketici]
        Processor[Mesaj İşleyici]
        RAG[RAG Sohbet İşleyici]
        Retriever[Vektör Retriever]
        WebSearch[Web Arama Aracı]
        LLM[LLM İstemcisi]
    end

    subgraph "Veri Katmanı"
        VectorDB[ChromaDB]
        Redis[Redis Cache]
    end

    UI --> Store
    Store --> Hook
    Hook --> API
    Hook <--> SignalRClient

    API --> Endpoint
    Endpoint --> EventBus
    EventBus --> Exchange
    Exchange --> Queue
    Queue --> Consumer

    Consumer --> Processor
    Processor --> RAG
    RAG --> Retriever
    Retriever --> VectorDB
    Processor --> WebSearch
    RAG --> LLM

    Processor --> EventBus
    EventBus --> Exchange
    Exchange --> Handler
    Handler --> SignalRHub
    SignalRHub --> SignalRClient

    Processor --> Redis
    Queue -.-> DLQ

    style UI fill:#e1f5ff
    style SignalRHub fill:#ffe1e1
    style Exchange fill:#e1ffe1
    style LLM fill:#ffe1ff
```

## Özet

LLM sohbet istek akışı aşağıdaki temel özelliklere sahip sağlam, olay tabanlı bir mimari uygular:

1. **Asenkron İşleme** - Engelleyici olmayan istek/yanıt deseni
2. **Olay Tabanlı** - RabbitMQ hizmetler arasında gevşek bağlantı sağlar
3. **Gerçek Zamanlı Güncellemeler** - SignalR anlık yanıt teslimatı sağlar
4. **Ölçeklenebilir** - Birden fazla AI Agent örneği aynı kuyruğu tüketebilir
5. **Dayanıklı** - Dead letter kuyrukları başarısız mesajları işler
6. **Gözlemlenebilir** - Korelasyon ID'leri hizmetler arası istekleri takip eder
7. **Geliştirilmiş Bağlam** - Doğru yanıtlar için RAG + isteğe bağlı Web Arama

Akış, sistem güvenilirliği ve ölçeklenebilirliğini korurken gerçek zamanlı AI yanıtlarıyla sorunsuz bir kullanıcı deneyimi sağlar.
