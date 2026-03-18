# BlogApp AI Agent Service - Dokümantasyon Dosyaları

Bu dizinde, BlogApp AI Agent Service için kapsamlı mimari dokümantasyon dosyaları bulunmaktadır.

## 📁 Dokümantasyon Dosyaları

### 1. blog_app_ai_agent.md (45 KB)
- **Türkçe mimari dokümantasyon**
- 12 bölümlük detaylı açıklamalar
- Mermaid diyagramları
- Önemli kod snippet'leri
- İçindekiler ve akış diyagramları

### 2. blog_app_ai_agent_complete.md (324 KB) ⭐
- **TÜM Python kaynak kodlarını içerir**
- **75 Python dosyasının tam kaynak kodu**
- Her dosyanın ayrıntılı kod listing'i
- Tüm katmanların (Core, Domain, Infrastructure, Services, API, RAG, Messaging, Tools, Strategies) komple kodları
- **YENİ ÖZELLİKLER:** Circuit Breaker, Multi-Level Cache, Rate Limiting, Streaming Support

## 📊 Proje İstatistikleri

| Kategori | Dosya Sayısı |
|----------|--------------|
| Core | 10 |
| Domain (Interfaces + Entities) | 13 |
| Infrastructure (Adapters) | 13 |
| Services | 8 |
| RAG Components | 5 |
| Messaging | 3 |
| API Layer | 9 |
| AI Agents | 4 |
| Tools | 2 |
| GEO Strategies | 8 |
| **TOPLAM** | **75** |

## 🚀 Hızlı Başlangıç

### Tam Kaynak Kodu Okumak İçin:
```bash
cat blog_app_ai_agent_complete.md
```

### Mimari Özeti Görmek İçin:
```bash
cat blog_app_ai_agent.md
```

## 📖 Dokümantasyon İçeriği

### blog_app_ai_agent_complete.md - Tam Kod Listesi

Bu dosya şu bölümleri içerir:

#### 1. Core Bileşenler (10 dosya)
- `main.py` - Uygulama giriş noktası
- `core/config.py` - Pydantic Settings ile konfigürasyon
- `core/cache.py` - Redis cache wrapper
- `core/security.py` - API key authentication
- `core/auth.py` - Authentication utilities
- `core/sanitizer.py` - Prompt injection koruması
- `core/exceptions.py` - Custom exceptions
- `core/logging_utils.py` - Loglama araçları
- `core/circuit_breaker.py` - **YENİ:** Circuit Breaker pattern for error recovery
- `core/multi_level_cache.py` - **YENİ:** L1/L2/L3 cache hierarchy
- `core/rate_limits.py` - **YENİ:** Endpoint-based rate limiting configuration

#### 2. Domain Katmanı (13 dosya)

**Interfaces (6 dosya):**
- `i_llm_provider.py` - LLM provider interface
- `i_cache.py` - Cache interface
- `i_vector_store.py` - Vector store interface
- `i_embedding_provider.py` - Embedding provider interface
- `i_message_broker.py` - Message broker interface
- `i_web_search.py` - Web search interface

**Entities (7 dosya):**
- `article.py` - Article entity
- `chat.py` - Chat entity
- `analysis.py` - Analysis entity
- `ai_generation.py` - AI generation entity

#### 3. Infrastructure Katmanı (13 dosya)
- `ollama_adapter.py` - Ollama LLM implementation
- `redis_adapter.py` - Redis cache implementation
- `chroma_adapter.py` - ChromaDB vector store
- `ollama_embedding_adapter.py` - Ollama embeddings (nomic-embed-text)
- `rabbitmq_adapter.py` - RabbitMQ messaging
- `duckduckgo_adapter.py` - DuckDuckGo web search

#### 4. Services Katmanı (8 dosya)
- `analysis_service.py` - Blog content analysis
- `chat_service.py` - RAG-powered chat
- `seo_service.py` - SEO & GEO optimization
- `rag_service.py` - RAG operations
- `indexing_service.py` - Article indexing
- `content_cleaner.py` - Content sanitization
- `message_processor_service.py` - Message processing

#### 5. RAG Bileşenleri (5 dosya)
- `chunker.py` - Markdown-aware text chunking
- `embeddings.py` - Embedding service
- `retriever.py` - Semantic retrieval
- `vector_store.py` - ChromaDB wrapper

#### 6. Messaging (3 dosya)
- `consumer.py` - RabbitMQ consumer
- `processor.py` - Message processor

#### 7. API Katmanı (9 dosya)
- `routes.py` - FastAPI application factory
- `dependencies.py` - Dependency Injection container
- `health.py` - Health check endpoints
- `analysis.py` - Content analysis endpoints
- `chat.py` - Chat endpoints

#### 8. AI Agent'ler (4 dosya)
- `simple_blog_agent.py` - Direct LLM agent (RAG-free)
- `rag_chat_handler.py` - RAG chat handler
- `indexer.py` - Article indexer

#### 9. Tools (2 dosya)
- `web_search.py` - DuckDuckGo search tool

#### 10. GEO Stratejileri (8 dosya)
- `base.py` - IGeoStrategy interface
- `factory.py` - GeoStrategyFactory
- `tr_strategy.py` - Turkey optimization
- `us_strategy.py` - USA optimization
- `uk_strategy.py` - UK optimization
- `de_strategy.py` - Germany optimization

## 🏗️ Mimari Prensipleri

1. **Hexagonal Architecture** - Port & Adapters deseni
2. **Dependency Inversion** - Bağımlılıklar injection üzerinden
3. **Single Responsibility** - Her sınıf tek bir sorumluluğa sahip
4. **Open/Closed Principle** - GEO stratejileri eklenebilir
5. **Interface Segregation** - Minimal arayüzler
6. **Strategy Pattern** - GEO optimizasyonu için
7. **Factory Pattern** - Strategy oluşturma için
8. **Circuit Breaker Pattern** - **YENİ:** Hata kurtarma ve dayanıklılık
9. **Multi-Level Caching** - **YENİ:** L1/L2/L3 cache hiyerarşisi
10. **Rate Limiting** - **YENİ:** Endpoint bazlı dinamik rate limiting

## 🔗 İlişkili Dosyalar

- **Dockerfile** - Container konfigürasyonu
- **requirements.txt** - Python bağımlılıkları
- **.env** - Environment variables
- **.env.example** - Örnek konfigürasyon

## 📝 Notlar

- Tüm kodlar orijinal haliyle korunmuştur
- Python type hints kullanılmıştır
- Async/await pattern ile asenkron işlem
- Pydantic ile veri doğrulama
- FastAPI dependency injection
- Redis caching ve distributed locking
- RabbitMQ message processing with idempotency
- **YENİ:** Circuit Breaker pattern ile dayanıklılık artışı
- **YENİ:** Multi-level cache ile performans optimizasyonu
- **YENİ:** Rate limiting ile kaynak yönetimi
- **YENİ:** Streaming response desteği (planlandı)

---
**Oluşturma Tarihi:** 2026-01-27
**Sürüm:** 3.1.0
**Mimari:** Hexagonal Architecture (Ports & Adapters)
**Yeni Özellikler:** Circuit Breaker, Multi-Level Cache, Rate Limiting
