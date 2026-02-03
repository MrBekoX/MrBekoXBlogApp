# MrBekoX Blog Uygulamasi - Istek Yonlendirme Mimarisi

Bu dokuman, MrBekoX Blog uygulamasinin nginx tabanli istek yonlendirme mekanizmasini ve uçtan uca istek akislarini detayli olarak açiklamaktadir.

---

## Icerik

1. [Genel Sistem Mimarisi](#1-genel-sistem-mimarisi)
2. [Servis Yapisi ve Portlar](#2-servis-yapisi-ve-portlar)
3. [Nginx Istek Yonlendirme Mekanizmasi](#3-nginx-istek-yonlendirme-mekanizmasi)
4. [Ornek Senaryo 1: Blog Yazisi Goruntuleme](#4-ornek-senaryo-1-blog-yazisi-goruntuleme)
5. [Ornek Senaryo 2: Yeni Blog Yazisi Olusturma](#5-ornek-senaryo-2-yeni-blog-yazisi-olusturma)
6. [Ornek Senaryo 3: Arama Islemi](#6-ornek-senaryo-3-arama-islemi)
7. [Genel Istek Yonlendirme Diyagrami](#7-genel-istek-yonlendirme-diyagrami)
8. [Guvenlik Mekanizmalari](#8-guvenlik-mekanizmalari)
9. [Cache Stratejisi](#9-cache-stratejisi)

---

## 1. Genel Sistem Mimarisi

Sistem, modern bir microservices mimarisi kullanmaktadir. Tum istekler AWS ALB (Application Load Balancer) uzerinden HTTPS ile alinir, Nginx reverse proxy tarafindan yonlendirilir ve ilgili servislere iletilir.

```mermaid
flowchart TB
    subgraph Internet["Internet"]
        Client["Kullanici Tarayicisi<br/>(HTTPS)"]
    end

    subgraph AWS["AWS Altyapisi"]
        ALB["AWS Application Load Balancer<br/>(SSL/TLS Terminasyon)"]
    end

    subgraph Docker["Docker Network (blogapp-network)"]
        subgraph Nginx_Container["Nginx Container"]
            Nginx["Nginx Reverse Proxy<br/>:80"]
        end

        subgraph Frontend_Container["Frontend Container"]
            Frontend["Next.js 16 SSR<br/>:3000"]
        end

        subgraph API_Container["API Container"]
            API[".NET Core API<br/>:8080"]
        end

        subgraph Data_Layer["Veri Katmani"]
            PostgreSQL["PostgreSQL 16<br/>:5432"]
            Redis["Redis 7<br/>:6379"]
        end
    end

    Client -->|HTTPS| ALB
    ALB -->|HTTP| Nginx
    Nginx -->|/api/*, /hubs/*| API
    Nginx -->|/, /_next/*| Frontend
    API --> PostgreSQL
    API --> Redis
    Frontend -.->|Server-Side API Calls| API

    style Client fill:#e1f5fe
    style ALB fill:#fff3e0
    style Nginx fill:#e8f5e9
    style Frontend fill:#f3e5f5
    style API fill:#fff8e1
    style PostgreSQL fill:#e3f2fd
    style Redis fill:#ffebee
```

### Mimari Bilesenler

| Bilesen | Teknoloji | Port | Gorev |
|---------|-----------|------|-------|
| **ALB** | AWS Application Load Balancer | 443 (HTTPS) | SSL terminasyon, yuk dengeleme |
| **Nginx** | nginx:alpine | 80 | Reverse proxy, routing, guvenlik |
| **Frontend** | Next.js 16 + React 19 | 3000 | SSR/SSG, kullanici arayuzu |
| **API** | .NET Core 10 | 8080 | REST API, is mantigi |
| **PostgreSQL** | PostgreSQL 16 Alpine | 5432 | Ana veritabani |
| **Redis** | Redis 7 Alpine | 6379 | Cache, session, real-time |

---

## 2. Servis Yapisi ve Portlar

### Docker Network Yapisi

```mermaid
flowchart LR
    subgraph External["Dis Erisim"]
        Port80["Host :80"]
        Port8080["Host :8080"]
        Port3000["Host :3000"]
    end

    subgraph Network["blogapp-network (bridge)"]
        N["nginx:80"]
        F["frontend:3000"]
        A["api:8080"]
        P["postgres:5432"]
        R["redis:6379"]
    end

    Port80 --> N
    Port8080 --> A
    Port3000 --> F

    N --> F
    N --> A
    A --> P
    A --> R
```

### Container Detaylari

| Container | Image | Memory Limit | Health Check |
|-----------|-------|--------------|--------------|
| blogapp-nginx-prod | nginx:alpine | 32MB | - |
| blogapp-frontend-prod | mrbeko/blog-app:web-latest | 64MB | - |
| blogapp-api-prod | mrbeko/blog-app:api-latest | 300MB | - |
| blogapp-postgres-prod | postgres:16-alpine | 128MB | pg_isready |
| blogapp-redis-prod | redis:7-alpine | 64MB | redis-cli ping |

---

## 3. Nginx Istek Yonlendirme Mekanizmasi

Nginx, tum gelen istekleri URL pattern'ine gore uygun backend servisine yonlendirir.

### Routing Kurallari (Oncelik Sirasina Gore)

```mermaid
flowchart TD
    Request["Gelen Istek"] --> Check1{"/health?"}

    Check1 -->|Evet| Health["API Health Check<br/>api:8080/health"]
    Check1 -->|Hayir| Check2{"/api/v*/media/upload?"}

    Check2 -->|Evet| Upload["Media Upload<br/>api:8080<br/>Body Limit: 20MB"]
    Check2 -->|Hayir| Check3{"/api/*?"}

    Check3 -->|Evet| API["REST API<br/>api:8080<br/>Body Limit: 1MB"]
    Check3 -->|Hayir| Check4{"/hubs/*?"}

    Check4 -->|Evet| WS["WebSocket/SignalR<br/>api:8080<br/>Upgrade Headers"]
    Check4 -->|Hayir| Check5{"/_next/static/*?"}

    Check5 -->|Evet| Static["Static Assets<br/>frontend:3000<br/>Cache: 1 yil"]
    Check5 -->|Hayir| Frontend["Next.js App<br/>frontend:3000"]

    style Request fill:#e3f2fd
    style Health fill:#c8e6c9
    style Upload fill:#fff9c4
    style API fill:#fff9c4
    style WS fill:#f3e5f5
    style Static fill:#e0f2f1
    style Frontend fill:#f3e5f5
```

### Upstream Tanimlari

```nginx
# Frontend Upstream (Next.js)
upstream frontend {
    server frontend:3000;
    keepalive 8;
}

# API Upstream (.NET Core)
upstream api {
    server api:8080;
    keepalive 16;
}
```

### Routing Detaylari

| Pattern | Hedef | Body Limit | Ozel Ayarlar |
|---------|-------|------------|--------------|
| `/health` | api:8080 | 1MB | Logging kapali |
| `/api/v[0-9]+/media/upload` | api:8080 | 20MB | Dosya yukleme |
| `/api/*` | api:8080 | 1MB | REST API |
| `/hubs/*` | api:8080 | 1MB | WebSocket, 24s timeout |
| `/_next/static/*` | frontend:3000 | 1MB | 1 yil cache |
| `/` | frontend:3000 | 1MB | Catch-all |

---

## 4. Ornek Senaryo 1: Blog Yazisi Goruntuleme

Bu senaryo, bir kullanicinin `https://mrbekox.dev/posts/my-first-blog-post` adresine gidip bir blog yazisini goruntulemesini anlatmaktadir.

### Istek Akisi

```mermaid
sequenceDiagram
    autonumber
    participant U as Kullanici
    participant B as Tarayici
    participant ALB as AWS ALB
    participant N as Nginx
    participant F as Frontend (Next.js)
    participant A as API (.NET)
    participant C as Redis Cache
    participant DB as PostgreSQL

    Note over U,DB: Adim 1: Sayfa Istegi
    U->>B: mrbekox.dev/posts/my-first-blog-post
    B->>ALB: GET /posts/my-first-blog-post (HTTPS)
    ALB->>N: GET /posts/my-first-blog-post (HTTP)
    N->>N: Pattern: / (catch-all)
    N->>F: Proxy to frontend:3000

    Note over F,DB: Adim 2: Server-Side Rendering (SSR)
    F->>F: Route: /posts/[slug]/page.tsx
    F->>A: GET /api/v1/posts/slug/my-first-blog-post

    Note over A,DB: Adim 3: Cache Kontrolu
    A->>C: Cache key kontrolu

    alt Cache Hit
        C-->>A: Cached post data
    else Cache Miss
        A->>DB: SELECT * FROM posts WHERE slug = ?
        DB-->>A: Post verisi
        A->>C: Cache'e yaz (5 dk TTL)
    end

    A-->>F: JSON Response (Post data)

    Note over F,B: Adim 4: HTML Render
    F->>F: React SSR render
    F->>F: SEO meta tags ekle
    F->>F: Schema.org markup ekle
    F-->>N: HTML Response
    N-->>ALB: HTML Response + Security Headers
    ALB-->>B: HTML Response (HTTPS)
    B->>U: Sayfa gosterilir

    Note over B,F: Adim 5: Static Assets
    B->>ALB: GET /_next/static/chunks/...
    ALB->>N: Static asset istegi
    N->>F: Proxy to frontend:3000
    F-->>N: JS/CSS dosyalari
    N-->>B: Response (Cache: 1 yil)
```

### Detayli Açiklama

1. **Kullanici Istegi**: Kullanici tarayicida blog yazisinun URL'sini açar
2. **ALB SSL Terminasyonu**: HTTPS istegi HTTP'ye dönüsturulur
3. **Nginx Routing**: `/posts/*` pattern'i catch-all ile frontend'e yonlendirilir
4. **SSR Render**: Next.js server component'i çalisir
5. **API Çagrisi**: `fetchPostBySlug()` fonksiyonu backend API'yi çagirir
6. **Cache Kontrolu**: Redis'te 5 dakikalik cache kontrolu yapilir
7. **Database Sorgusu**: Cache miss durumunda PostgreSQL'den çekilir
8. **HTML Response**: Tam renderlanmis HTML kullaniciya gonderilir
9. **Hydration**: Client-side React hydration gerçeklesir

### Kullanilan Dosyalar

| Katman | Dosya | Islem |
|--------|-------|-------|
| Frontend | `src/app/posts/[slug]/page.tsx` | SSR page component |
| Frontend | `src/lib/server-api.ts` | `fetchPostBySlug()` |
| API | `Endpoints/PostsEndpoints.cs` | `GET /posts/slug/{slug}` |
| API | `Features/PostFeature/Queries/GetPostBySlugQuery` | MediatR handler |
| Infra | `Persistence/Repositories/EfCoreBlogPostRepository` | EF Core sorgusu |

---

## 5. Ornek Senaryo 2: Yeni Blog Yazisi Olusturma

Bu senaryo, admin panelinden yeni bir blog yazisi olusturmayi anlatmaktadir. Authentication gerektiren bir islemdir.

### Istek Akisi

```mermaid
sequenceDiagram
    autonumber
    participant U as Admin Kullanici
    participant B as Tarayici
    participant ALB as AWS ALB
    participant N as Nginx
    participant F as Frontend
    participant A as API (.NET)
    participant C as Redis
    participant DB as PostgreSQL

    Note over U,DB: Adim 1: Login Islemi (Onceden yapilmis)
    Note over B: HttpOnly Cookie: BlogApp.AccessToken<br/>HttpOnly Cookie: BlogApp.RefreshToken

    Note over U,DB: Adim 2: Yazi Olusturma Formu
    U->>B: Admin Panel > Yeni Yazi
    B->>ALB: GET /mrbekox-console/posts/new (HTTPS)
    ALB->>N: HTTP Request
    N->>F: Proxy to frontend:3000
    F-->>B: Yazi editoru sayfasi

    Note over U,DB: Adim 3: Yazi Gonderme
    U->>B: Form doldur ve kaydet
    B->>B: Zustand store'dan auth bilgisi
    B->>ALB: POST /api/v1/posts<br/>Cookie: BlogApp.AccessToken<br/>X-CSRF-TOKEN: [token]
    ALB->>N: HTTP Request (headers korunur)
    N->>N: Pattern: /api/*
    N->>A: Proxy to api:8080

    Note over A,DB: Adim 4: Authentication & Authorization
    A->>A: JWT Cookie dogrula
    A->>A: Claims: Role=Admin kontrol

    alt Token Gecersiz/Suresi Dolmus
        A-->>B: 401 Unauthorized
        B->>ALB: POST /api/v1/auth/refresh-token
        ALB->>N: HTTP Request
        N->>A: Refresh token istegi
        A->>DB: Refresh token kontrolu
        A-->>B: Yeni Access Token (Cookie)
        B->>ALB: POST /api/v1/posts (retry)
    end

    Note over A,DB: Adim 5: Yazi Kaydetme
    A->>A: Request validation (FluentValidation)
    A->>A: Slug olustur
    A->>DB: INSERT INTO posts VALUES (...)
    DB-->>A: Created post ID

    Note over A,C: Adim 6: Cache Invalidation
    A->>C: Cache key sil: posts_list_*
    A->>A: SignalR broadcast: CacheInvalidated

    A-->>N: 201 Created + Post JSON
    N-->>ALB: Response + Security Headers
    ALB-->>B: Response (HTTPS)
    B->>U: "Yazi olusturuldu" bildirimi

    Note over B,F: Adim 7: Real-time Guncelleme
    B->>A: SignalR: Subscribe to cache updates
    A-->>B: CacheInvalidated event
    B->>B: Zustand store guncelle
```

### Detayli Açiklama

1. **Authentication**: Kullanici önceden login olmali (HttpOnly cookie ile JWT)
2. **CSRF Koruması**: Her POST istegi X-CSRF-TOKEN header içermeli
3. **Authorization**: JWT claims üzerinden rol kontrolü (Admin, Editor, Author)
4. **Rate Limiting**: IP bazli rate limit kontrolu (300 req/min)
5. **Validation**: Request body FluentValidation ile dogrulanir
6. **Database Insert**: Post verisi PostgreSQL'e kaydedilir
7. **Cache Invalidation**: Ilgili cache key'leri temizlenir
8. **Real-time Sync**: SignalR ile diger clientlar bilgilendirilir

### Guvenlik Kontrolleri

```mermaid
flowchart LR
    Request["POST /api/v1/posts"] --> RateLimit{"Rate Limit<br/>300/dk"}

    RateLimit -->|Asim| Block["429 Too Many Requests"]
    RateLimit -->|OK| CSRF{"CSRF Token<br/>Gecerli mi?"}

    CSRF -->|Hayir| Reject1["403 Forbidden"]
    CSRF -->|Evet| JWT{"JWT Cookie<br/>Gecerli mi?"}

    JWT -->|Hayir| Reject2["401 Unauthorized"]
    JWT -->|Evet| Role{"Rol Yetkili mi?<br/>(Admin/Editor/Author)"}

    Role -->|Hayir| Reject3["403 Forbidden"]
    Role -->|Evet| Validate{"Validation<br/>Gecerli mi?"}

    Validate -->|Hayir| Reject4["400 Bad Request"]
    Validate -->|Evet| Process["Islemi Gerceklestir"]

    style Block fill:#ffcdd2
    style Reject1 fill:#ffcdd2
    style Reject2 fill:#ffcdd2
    style Reject3 fill:#ffcdd2
    style Reject4 fill:#ffcdd2
    style Process fill:#c8e6c9
```

---

## 6. Ornek Senaryo 3: Arama Islemi

Bu senaryo, kullanicinin blog yazilari arasinda arama yapmasini anlatmaktadir.

### Istek Akisi

```mermaid
sequenceDiagram
    autonumber
    participant U as Kullanici
    participant B as Tarayici
    participant ALB as AWS ALB
    participant N as Nginx
    participant F as Frontend
    participant A as API (.NET)
    participant DB as PostgreSQL

    Note over U,DB: Adim 1: Arama Istegi
    U->>B: Arama kutusuna "next.js" yaz
    B->>B: Debounce (300ms)

    Note over B,F: Adim 2: URL-based Navigation
    B->>ALB: GET /posts?search=next.js&page=1
    ALB->>N: HTTP Request
    N->>F: Proxy to frontend:3000

    Note over F,DB: Adim 3: Server-Side Search
    F->>F: URL params parse
    F->>A: GET /api/v1/posts?search=next.js&pageNumber=1&pageSize=10

    Note over A,DB: Adim 4: Full-Text Search
    A->>DB: PostgreSQL Full-Text Search<br/>WHERE search_vector @@ plainto_tsquery('next.js')

    Note right of DB: pg_trgm extension<br/>GIN index kullanimi<br/>Turkce dil destegi

    DB-->>A: Matched posts (paginated)
    A-->>F: JSON Response

    Note over F,B: Adim 5: Sonuclari Goster
    F->>F: SSR render search results
    F-->>N: HTML Response
    N-->>B: Response + Headers
    B->>U: Arama sonuclari gosterilir
```

### PostgreSQL Full-Text Search Yapisi

```sql
-- Search vector trigger (otomatik guncelleme)
CREATE TRIGGER posts_search_vector_trigger
    BEFORE INSERT OR UPDATE ON posts
    FOR EACH ROW
    EXECUTE FUNCTION posts_search_vector_update();

-- GIN Index (hizli arama)
CREATE INDEX idx_posts_search_vector
    ON posts USING GIN(search_vector);

-- Trigram Index (fuzzy matching)
CREATE INDEX idx_posts_title_trgm
    ON posts USING GIN(title gin_trgm_ops);
```

---

## 7. Genel Istek Yonlendirme Diyagrami

Sistemin tum istek turlerini kapsayan genel akis diyagrami:

```mermaid
flowchart TB
    subgraph Client["Kullanici Katmani"]
        Browser["Web Tarayici"]
        Mobile["Mobil Uygulama"]
    end

    subgraph Edge["Edge Katmani"]
        ALB["AWS ALB<br/>(SSL Terminasyon)"]
    end

    subgraph Gateway["Gateway Katmani"]
        Nginx["Nginx Reverse Proxy"]

        subgraph Nginx_Rules["Routing Kurallari"]
            R1["/health → API"]
            R2["/api/* → API"]
            R3["/hubs/* → API (WS)"]
            R4["/_next/static/* → Frontend (Cached)"]
            R5["/* → Frontend"]
        end
    end

    subgraph Application["Uygulama Katmani"]
        subgraph Frontend_App["Frontend"]
            NextJS["Next.js SSR"]
            React["React 19"]
            Zustand["Zustand Store"]
        end

        subgraph API_App["Backend API"]
            ASPNET[".NET Core"]
            MediatR["MediatR (CQRS)"]
            SignalR["SignalR Hub"]
        end
    end

    subgraph Data["Veri Katmani"]
        PostgreSQL["PostgreSQL<br/>(Ana DB)"]
        Redis["Redis<br/>(Cache/Session)"]
        FileSystem["File System<br/>(Uploads)"]
    end

    Browser --> ALB
    Mobile --> ALB
    ALB --> Nginx

    Nginx --> NextJS
    Nginx --> ASPNET

    NextJS --> React
    React --> Zustand
    NextJS -.-> ASPNET

    ASPNET --> MediatR
    ASPNET --> SignalR

    MediatR --> PostgreSQL
    MediatR --> Redis
    ASPNET --> FileSystem

    SignalR -.->|Real-time| Browser

    style ALB fill:#fff3e0
    style Nginx fill:#e8f5e9
    style NextJS fill:#f3e5f5
    style ASPNET fill:#fff8e1
    style PostgreSQL fill:#e3f2fd
    style Redis fill:#ffebee
```

### Istek Turleri ve Akislari

```mermaid
flowchart LR
    subgraph Requests["Istek Turleri"]
        GET_Page["GET Sayfa<br/>(/, /posts, /about)"]
        GET_API["GET API<br/>(/api/v1/posts)"]
        POST_API["POST API<br/>(/api/v1/posts)"]
        WS["WebSocket<br/>(/hubs/cache)"]
        Static["Static<br/>(/_next/static/*)"]
        Upload["Upload<br/>(/api/v1/media/upload)"]
    end

    subgraph Routing["Nginx Routing"]
        Frontend_Route["→ frontend:3000"]
        API_Route["→ api:8080"]
        API_WS["→ api:8080<br/>(Upgrade)"]
        API_Upload["→ api:8080<br/>(20MB limit)"]
    end

    GET_Page --> Frontend_Route
    Static --> Frontend_Route
    GET_API --> API_Route
    POST_API --> API_Route
    WS --> API_WS
    Upload --> API_Upload
```

---

## 8. Guvenlik Mekanizmalari

### Katmanli Guvenlik Yapisi

```mermaid
flowchart TB
    subgraph Layer1["Katman 1: Edge Guvenlik"]
        ALB_SSL["SSL/TLS (ALB)"]
        HSTS["HSTS (1 yil)"]
    end

    subgraph Layer2["Katman 2: Nginx Guvenlik"]
        Headers["Security Headers"]
        CSP["Content Security Policy"]
        RateLimit_Nginx["Connection Limiting"]
    end

    subgraph Layer3["Katman 3: API Guvenlik"]
        RateLimit["IP Rate Limiting"]
        CSRF["CSRF Protection"]
        JWT["JWT Authentication"]
        RBAC["Role-Based Access"]
    end

    subgraph Layer4["Katman 4: Veri Guvenlik"]
        Validation["Input Validation"]
        Sanitization["Data Sanitization"]
        Encryption["Password Hashing"]
    end

    Layer1 --> Layer2 --> Layer3 --> Layer4
```

### Security Headers

| Header | Deger | Amac |
|--------|-------|------|
| X-Frame-Options | DENY | Clickjacking koruması |
| X-Content-Type-Options | nosniff | MIME sniffing koruması |
| X-XSS-Protection | 1; mode=block | XSS filtresi |
| Referrer-Policy | strict-origin-when-cross-origin | Referrer gizliligi |
| Strict-Transport-Security | max-age=31536000 | HTTPS zorunlulugu |
| Content-Security-Policy | [strict policy] | XSS/injection koruması |

### Rate Limiting Kurallari

| Endpoint | Limit | Periyot |
|----------|-------|---------|
| Genel | 300 | /dakika |
| Login | 5 | /dakika |
| Register | 10 | /saat |
| Image Upload | 10 | /dakika |
| Bulk Upload | 5 | /5 dakika |

---

## 9. Cache Stratejisi

### Cache Katmanlari

```mermaid
flowchart TB
    subgraph L1["Katman 1: CDN/Browser Cache"]
        Browser["Browser Cache<br/>(Static: 1 yil)"]
    end

    subgraph L2["Katman 2: Nginx Cache"]
        Nginx_Cache["Static Asset Cache<br/>(/_next/static/*)"]
    end

    subgraph L3["Katman 3: Application Cache"]
        Output["Output Cache<br/>(.NET)"]
        ISR["ISR Cache<br/>(Next.js)"]
    end

    subgraph L4["Katman 4: Data Cache"]
        Redis_Cache["Redis Cache<br/>(Query Results)"]
    end

    subgraph L5["Katman 5: Database"]
        PG["PostgreSQL<br/>(Query Cache)"]
    end

    L1 --> L2 --> L3 --> L4 --> L5
```

### Cache Sureleri

| Icerik Tipi | Sure | Katman |
|-------------|------|--------|
| Static Assets | 1 yil (immutable) | Browser/Nginx |
| Posts Listesi | 1 dakika | Output Cache |
| Post Detay | 5 dakika | Output Cache + Redis |
| Kategoriler | 10 dakika | Output Cache |
| Etiketler | 10 dakika | Output Cache |
| Sitemap | 1 saat | Output Cache |
| Robots.txt | 24 saat | Output Cache |
| RSS Feed | 30 dakika | Output Cache |

### Cache Invalidation

```mermaid
sequenceDiagram
    participant Admin
    participant API
    participant Redis
    participant SignalR
    participant Clients

    Admin->>API: POST/PUT/DELETE islem
    API->>API: Veritabani guncelle
    API->>Redis: Ilgili cache key'leri sil
    API->>SignalR: CacheInvalidated event
    SignalR-->>Clients: Broadcast notification
    Clients->>Clients: Local state guncelle
```

---

## Sonuç

Bu dokuman, MrBekoX Blog uygulamasinin nginx tabanli istek yonlendirme mekanizmasini kapsamli sekilde açiklamistir. Sistem, modern microservices mimarisi, katmanli guvenlik ve verimli cache stratejisi ile production-ready bir altyapi sunmaktadir.

### Temel Özellikler

- **Yuk Dengeleme**: AWS ALB ile HTTPS terminasyonu
- **Reverse Proxy**: Nginx ile akilli routing
- **SSR**: Next.js ile server-side rendering
- **Caching**: Cok katmanli cache stratejisi
- **Guvenlik**: HSTS, CSP, JWT, CSRF, Rate Limiting
- **Real-time**: SignalR ile anlık guncellemeler
- **Olçeklenebilirlik**: Docker container mimarisi

---

*Bu dokuman Claude Code tarafindan olusturulmustur.*
*Son guncelleme: 2026-01-14*
