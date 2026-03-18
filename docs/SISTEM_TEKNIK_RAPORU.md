# BlogApp Sistem Teknik Raporu

**Tarih:** 2026-01-31
**Sürüm:** 1.0
**Hazarlayan:** Claude Code Agent

---

## 📋 İçindekiler

1. [Sistem Genel Bakış](#1-sistem-genel-bakış)
2. [Frontend Mimarisi (Next.js)](#2-frontend-mimarisi-nextjs)
3. [Backend Mimarisi (.NET)](#3-backend-mimarisi-net)
4. [Building Blocks (Paylaşılan Bileşenler)](#4-building-blocks-paylaşılan-bileşenler)
5. [AI Agent Service](#5-ai-agent-service)
6. [Teknoloji Stack Özeti](#6-teknoloji-stack-özeti)
7. [Veri Akışı Diyagramları](#7-veri-akışı-diyagramları)
8. [Güvenlik Mimarisi](#8-güvenlik-mimarisi)
9. [Performans Optimizasyonları](#9-performans-optimizasyonları)
10. [Deployment Stratejisi](#10-deployment-stratejisi)

---

## 1. Sistem Genel Bakış

BlogApp, modern **mikroservis mimarisi** ile tasarlanmış, AI destekli bir blog platformudur. Sistem dört ana bileşenden oluşur:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BLOGAPP SİSTEMİ                              │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │   Next.js    │  │   .NET API   │  │  AI Service  │               │
│  │  Frontend    │◄─┤   Backend    │◄─┤   (Python)   │               │
│  │  (Client)    │  │   (Server)   │  │   (Ollama)   │               │
│  └──────────────┘  └──────┬───────┘  └──────┬───────┘               │
│                            │                  │                       │
│                      ┌─────▼─────┐    ┌──────▼──────┐               │
│                      │  RabbitMQ │    │   Ollama    │               │
│                      │ (Events)  │    │  (LLM)      │               │
│                      └───────────┘    └─────────────┘               │
│                            │                                        │
│                      ┌─────▼─────┐    ┌──────┐                      │
│                      │  Redis    │    │ Post │                      │
│                      │  (Cache)  │    │  SQL │                      │
│                      └───────────┘    └──────┘                      │
│                            │                                        │
│                      ┌─────▼─────┐    ┌──────┐                      │
│                      │ ChromaDB  │    │Signal│                      │
│                      │ (Vectors) │    │  R   │                      │
│                      └───────────┘    └──────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.1 Bileşenler

| Bileşen | Teknoloji | Amaç |
|---------|----------|------|
| **Frontend** | Next.js 16 + React 19 | Kullanıcı arayüzü, SSR, ISR |
| **Backend** | .NET 10.0 | REST API, Business Logic, Veri Yönetimi |
| **Building Blocks** | .NET 10.0 | Paylaşılan altyapı (Cache, Messaging) |
| **AI Service** | Python 3.12 + FastAPI | AI işleme, RAG, LLM entegrasyonu |

### 1.2 İletişim Protokolleri

- **REST API**: Frontend ↔ Backend
- **SignalR/WebSocket**: Backend → Frontend (real-time)
- **RabbitMQ (AMQP)**: Backend ↔ AI Service (event-driven)
- **gRPC**: Gelecek implementasyon için hazırlıklı

---

## 2. Frontend Mimarisi (Next.js)

### 2.1 Proje Yapısı

```
src/blogapp-web/
├── app/                          # Next.js App Router (Server Components)
│   ├── actions/                  # Server Actions
│   ├── dashboard/                # Dashboard rotaları
│   ├── mrbekox-console/          # Admin konsolu
│   ├── posts/[slug]/             # Dinamik post sayfaları
│   ├── layout.tsx                # Root layout
│   ├── page.tsx                  # Ana sayfa
│   ├── robots.ts                 # SEO robots.txt
│   └── sitemap.ts                # Dinamik sitemap
├── components/                   # React bileşenleri
│   ├── admin/                    # Admin bileşenleri
│   ├── auth/                     # Authentication (AuthGuard)
│   ├── chat/                     # AI Chat paneli
│   ├── comments/                 # Yorum sistemi
│   ├── layout/                   # Header, Footer
│   ├── posts/                    # Post kartları, listeler
│   ├── seo/                      # Schema.org JSON-LD
│   ├── ui/                       # shadcn/ui bileşenleri (23 adet)
│   └── cache-sync-provider.tsx   # Global cache sync
├── hooks/                        # Custom React hooks
│   ├── use-cache-sync.ts         # SignalR cache sync
│   ├── use-article-chat.ts       # Makale sohbeti
│   ├── use-cache-synced-data.ts  # Cache-aware data fetching
│   └── use-ai-analysis.ts        # AI analiz hook'u
├── lib/                          # Utility fonksiyonları
│   ├── api.ts                    # Client-side API (Axios)
│   ├── server-api.ts             # Server-side API (fetch)
│   └── utils.ts                  # Yardımcı fonksiyonlar
├── stores/                       # Zustand state management
│   ├── auth-store.ts             # Authentication state
│   ├── posts-store.ts            # Posts state (5dk cache)
│   ├── categories-store.ts       # Categories state
│   ├── tags-store.ts             # Tags state
│   └── chat-store.ts             # Chat state
└── types/                        # TypeScript tipleri
    └── index.ts                  # Tüm tipler
```

### 2.2 Teknoloji Stack

#### Core Framework
- **Next.js**: 16.1.1 (App Router, Server Components, Standalone output)
- **React**: 19.2.3
- **TypeScript**: 5.x

#### UI & Styling
- **TailwindCSS**: 4.x with PostCSS
- **shadcn/ui**: "new-york" style (Radix UI primitives)
- **Radix UI**: Avatar, Dialog, Dropdown, Navigation, Select, Tabs, Sheet
- **@tailwindcss/typography**: 0.5.19 (Markdown styling)
- **next-themes**: 0.4.6 (Dark mode)
- **cmdk**: 1.1.1 (Command palette - Cmd+K)
- **lucide-react**: 0.562.0 (Icons)

#### Markdown & Code
- **react-markdown**: 10.1.0
- **@uiw/react-md-editor**: 4.0.11
- **react-syntax-highlighter**: 16.1.0
- **rehype-highlight**: 7.0.2
- **remark-gfm**: 4.0.1 (GitHub Flavored Markdown)

#### State & Data Fetching
- **zustand**: 5.0.9 (State management with persist middleware)
- **axios**: 1.13.2 (Client-side HTTP)
- **@microsoft/signalr**: 10.0.0 (Real-time WebSocket)

#### Forms & Validation
- **react-hook-form**: 7.69.0
- **@hookform/resolvers**: 5.2.2
- **zod**: 4.2.1

#### SEO & Metadata
- **schema-dts**: 1.1.5 (JSON-LD structured data)

### 2.3 Routing Stratejisi

#### App Router Kullanımı
- **Server Components by Default**: Tüm sayfalar RSC (optimal performans)
- **Mixed Rendering**: Hibrit SSR/CSR yaklaşımı

| Route | Rendering | Açıklama |
|-------|-----------|----------|
| `/` | SSR | Ana sayfa - server-side data fetching |
| `/posts` | SSR | Post listesi - cache sync ile |
| `/posts/[slug]` | ISR (60s) | Dinamik post sayfaları |
| `/login` | CSR | Login sayfası |
| `/register` | CSR | Kayıt sayfası |
| `/mrbekox-console/*` | CSR + AuthGuard | Korumalı admin rotaları |

### 2.4 State Management (Zustand)

#### Auth Store
```typescript
// stores/auth-store.ts
interface AuthStore {
  authStatus: 'idle' | 'checking' | 'authenticated' | 'unauthenticated'
  user: User | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  checkAuth: () => Promise<void>
}
```

**Özellikler:**
- HttpOnly cookie tabanlı JWT
- `idle` durumu sadece ilk ziyaret kontrolü için
- Infinite loop önleme (in-flight promise tracking)
- localStorage persist

#### Posts Store
```typescript
// stores/posts-store.ts
interface PostsStore {
  posts: Post[]
  lastFetched: number
  cacheVersion: number  // Reactive cache invalidation
  fetchPosts: () => Promise<void>
  invalidateCache: () => void
}
```

**Cache Stratejisi:**
- 5 dakika in-memory cache
- Timestamp validation
- Optimistic updates + rollback
- Query parameter bazlı cache ayrımı

### 2.5 API Entegrasyonu

#### Client-Side API (Axios)
```typescript
// lib/api.ts
const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5116/api/v1',
  withCredentials: true,  // HttpOnly cookies
})

// Otomatik token refresh
apiClient.interceptors.response.use(
  response => response,
  async error => {
    if (error.response?.status === 401 && !refreshInProgress) {
      return attemptTokenRefresh()
    }
  }
)
```

**API Modülleri:**
- `authApi` - login, register, logout, refreshToken
- `postsApi` - getAll, create, update, delete, publish, getMyPosts
- `categoriesApi` - getAll, create, update, delete
- `tagsApi` - getAll, create, delete
- `commentsApi` - getByPostId, create, approve, delete
- `aiApi` - generateTitle, generateExcerpt, generateTags
- `chatApi` - sendMessage
- `mediaApi` - uploadImage, uploadImages, deleteImage

#### Server-Side API (Fetch)
```typescript
// lib/server-api.ts
export async function fetchPosts(): Promise<Post[]> {
  const res = await fetch(`${API_URL}/posts`, {
    next: { revalidate: 60, tags: ['posts'] }  // ISR
  })
  return res.json()
}
```

**ISR Revalidation:**
- Posts: 60 saniye
- Categories/Tags: 300 saniye
- On-demand revalidation (Server Actions)

### 2.6 Real-Time Özellikler

#### SignalR Cache Sync
```typescript
// hooks/use-cache-sync.ts
const connection = new HubConnectionBuilder()
  .withUrl(`${API_URL}/hubs/cache`)
  .withAutomaticReconnect([0, 2000, 5000, 10000])  // Exponential backoff
  .build()

connection.on('CacheInvalidated', (message) => {
  // Backend cache değiştiğinde frontend'i güncelle
  postsStore.invalidateCache()
})
```

**Event Tipleri:**
- `CacheInvalidated` - Cache sync
- `ChatMessageReceived` - AI chat streaming responses

#### SignalR Hub URL
```
/hubs/cache
```

**Subscribe Groups:**
- `posts_list`
- `categories_list`
- `tags_list`

### 2.7 Authentication Mimarisi

#### AuthGuard Component
```typescript
// components/auth/auth-guard.tsx
export function AuthGuard({
  children,
  allowedRoles = [UserRole.Admin, UserRole.Editor]
}: AuthGuardProps) {
  const { authStatus, user } = useAuthStore()

  if (authStatus === 'idle') {
    checkAuth()  // İlk kontrol
    return <LoadingSkeleton />
  }

  if (authStatus === 'unauthenticated') {
    redirect('/login')
  }

  if (!allowedRoles.includes(user!.role)) {
    return <AccessDenied />
  }

  return children
}
```

#### Cookie Yapılandırması
```
BlogApp.AccessToken  - JWT access token
BlogApp.RefreshToken - Refresh token

Ayarlar:
- HttpOnly: true (XSS koruması)
- Secure: true (HTTPS sadece)
- SameSite: Strict (CSRF koruması)
```

### 2.8 SEO Özellikleri

#### Dynamic Metadata
```typescript
// app/posts/[slug]/page.tsx
export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const post = await fetchPostBySlug(params.slug)

  return {
    title: post.title,
    description: post.excerpt,
    openGraph: {
      title: post.title,
      description: post.excerpt,
      images: [post.coverImage],
      type: 'article',
      publishedTime: post.publishedAt,
      authors: [post.author.fullName]
    }
  }
}
```

#### Schema.org Structured Data
```typescript
// components/seo/json-ld.tsx
export function JsonLd({ schema }: { schema: WithContext<Thing> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
    />
  )
}
```

**Schema Tipleri:**
- BlogPosting
- Breadcrumb
- Organization
- Person
- WebSite

#### Robots.txt
```typescript
// app/robots.ts
export default function robots(): Robots {
  return {
    rules: [
      { userAgent: '*', allow: '/' },
      { userAgent: '*', disallow: ['/mrbekox-console', '/api'] }
    ],
    sitemap: `${SITE_URL}/sitemap.xml`
  }
}
```

#### Dynamic Sitemap
```typescript
// app/sitemap.ts
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const posts = await fetchPublishedPosts()

  return [
    { url: SITE_URL, lastModified: new Date(), priority: 1 },
    { url: `${SITE_URL}/posts`, lastModified: new Date(), priority: 0.9 },
    ...posts.map(post => ({
      url: `${SITE_URL}/posts/${post.slug}`,
      lastModified: post.updatedAt,
      priority: 0.8,
      changeFrequency: 'weekly' as const
    }))
  ]
}
```

---

## 3. Backend Mimarisi (.NET)

### 3.1 Çözüm Yapısı

```
src/BlogApp.Server/
├── BlogApp.Server.Api/          # Presentation Layer
│   ├── Program.cs               # Application entry point
│   ├── Endpoints/               # Minimal API endpoints
│   ├── Hubs/                    # SignalR hubs
│   ├── Middlewares/             # Custom middlewares
│   └── Helpers/                 # Helper classes
├── BlogApp.Server.Application/  # Application Layer
│   ├── Features/                # Feature modules (CQRS)
│   │   ├── AuthFeature/
│   │   ├── PostFeature/
│   │   ├── CategoryFeature/
│   │   ├── TagFeature/
│   │   └── AiFeature/
│   ├── Common/
│   │   ├── Behaviors/           # MediatR pipeline behaviors
│   │   ├── BusinessRuleEngine/  # Business rules
│   │   ├── Interfaces/          # Abstractions
│   │   ├── Models/              # DTOs
│   │   └── Options/             # Configuration classes
│   └── DependencyInjection.cs
├── BlogApp.Server.Domain/       # Domain Layer
│   ├── Entities/                # Domain entities
│   ├── ValueObjects/            # Value objects
│   ├── Enums/                   # Enums
│   └── Exceptions/              # Domain exceptions
└── BlogApp.Server.Infrastructure/ # Infrastructure Layer
    ├── Persistence/
    │   ├── AppDbContext.cs      # EF Core DbContext
    │   ├── Configurations/      # EF configurations
    │   ├── Migrations/          # DB migrations
    │   ├── Repositories/        # Repository implementations
    │   └── DbSeeder.cs          # Database seeder
    └── Services/                # Infrastructure services
```

### 3.2 Teknoloji Stack

#### .NET Framework
- **Target Framework**: .NET 10.0
- **C# Features**: Nullable reference types, Primary constructors, Pattern matching

#### Key NuGet Packages

**API Project:**
| Package | Version | Purpose |
|---------|---------|---------|
| Microsoft.AspNetCore.Authentication.JwtBearer | 10.0.1 | JWT Authentication |
| AspNetCoreRateLimit | 5.0.0 | Rate limiting |
| Serilog.AspNetCore | 10.0.0 | Structured logging |
| Swashbuckle.AspNetCore | 10.1.0 | OpenAPI/Swagger |
| Asp.Versioning.Http | 8.1.0 | API Versioning |
| OpenTelemetry.Exporter.Prometheus.AspNetCore | 1.14.0-beta.1 | Metrics |

**Application Project:**
| Package | Version | Purpose |
|---------|---------|---------|
| MediatR | 14.0.0 | CQRS/Mediator pattern |
| FluentValidation | 12.1.1 | Request validation |
| AutoMapper | 16.0.0 | Object mapping |
| BCrypt.Net-Next | 4.0.3 | Password hashing |

**Infrastructure Project:**
| Package | Version | Purpose |
|---------|---------|---------|
| Npgsql.EntityFrameworkCore.PostgreSQL | 10.0.0 | PostgreSQL provider |
| Microsoft.EntityFrameworkCore | 10.0.1 | EF Core ORM |
| SixLabors.ImageSharp | 3.1.12 | Image processing |
| System.IdentityModel.Tokens.Jwt | 8.15.0 | JWT token handling |

### 3.3 Clean Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    BlogApp.Server.Api                        │
│                    (Presentation Layer)                      │
│  - Minimal API Endpoints                                    │
│  - Middleware Pipeline                                      │
│  - SignalR Hubs                                             │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│              BlogApp.Server.Application                      │
│               (Application Layer)                            │
│  - CQRS with MediatR (Commands/Queries)                     │
│  - Pipeline Behaviors (Validation, Logging, Caching)         │
│  - Business Rules Engine                                     │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                BlogApp.Server.Domain                         │
│                  (Domain Layer)                              │
│  - Entities, Value Objects, Enums                           │
│  - Domain Exceptions                                         │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│            BlogApp.Server.Infrastructure                     │
│              (Infrastructure Layer)                          │
│  - Entity Framework Core                                     │
│  - Repository Pattern                                       │
│  - External Services (JWT, Cache, RabbitMQ)                 │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 CQRS Pattern

#### Feature Yapısı
```
Features/
├── AuthFeature/
│   ├── Commands/
│   │   ├── LoginCommand/
│   │   │   ├── LoginCommandRequest.cs
│   │   │   ├── LoginCommandResponse.cs
│   │   │   ├── LoginCommandHandler.cs
│   │   │   └── Validators/
│   │   └── RefreshTokenCommand/
├── PostFeature/
│   ├── Commands/
│   │   ├── CreatePostCommand/
│   │   ├── UpdatePostCommand/
│   │   ├── DeletePostCommand/
│   │   ├── PublishPostCommand/
│   │   └── GenerateAiSummaryCommand/
│   └── Queries/
│       ├── GetPostsListQuery/
│       ├── GetPostByIdQuery/
│       └── GetPostBySlugQuery/
```

#### MediatR Pipeline Behaviors
```
1. LoggingBehavior       - Request/Response loglama
2. CachingBehavior       - Cache kontrolü ve yönetimi
3. ValidationBehavior    - FluentValidation
```

### 3.5 Repository Pattern

#### Entity-Specific Repositories
```
Repositories/
├── EfCoreReadRepository.cs              # Generic Read
├── EfCoreWriteRepository.cs             # Generic Write
├── UnitOfWork.cs                        # Transaction management
├── EfCoreBlogPostRepository/
│   ├── EfCoreBlogPostReadRepository.cs
│   └── EfCoreBlogPostWriteRepository.cs
├── EfCoreCategoryRepository/
├── EfCoreTagRepository/
├── EfCoreUserRepository/
└── EfCoreCommentRepository/
```

#### Repository Interfaces
```csharp
// Generic interfaces
IRepository<T>          # Combined read/write
IReadRepository<T>      # Read operations
IWriteRepository<T>     # Write operations

// Entity-specific
IBlogPostReadRepository / IBlogPostWriteRepository
ICategoryReadRepository / ICategoryWriteRepository
ITagReadRepository / ITagWriteRepository
IUserReadRepository / IUserWriteRepository
ICommentReadRepository / ICommentWriteRepository
IRefreshTokenReadRepository / IRefreshTokenWriteRepository
```

### 3.6 Unit of Work Pattern

```csharp
// UnitOfWork.cs
public interface IUnitOfWork : IDisposable
{
    // Read Repositories
    IBlogPostReadRepository PostsRead { get; }
    ICategoryReadRepository CategoriesRead { get; }
    ITagReadRepository TagsRead { get; }

    // Write Repositories
    IBlogPostWriteRepository PostsWrite { get; }
    ICategoryWriteRepository CategoriesWrite { get; }
    ITagWriteRepository TagsWrite { get; }

    Task<int> SaveChangesAsync(CancellationToken ct);
    Task BeginTransactionAsync(IsolationLevel isolationLevel, CancellationToken ct);
    Task CommitTransactionAsync(CancellationToken ct);
    Task RollbackTransactionAsync(CancellationToken ct);
}
```

### 3.7 Domain Model

#### Entities
| Entity | Açıklama | Özellikler |
|--------|----------|------------|
| **BlogPost** | Blog makalesi | Title, Slug, Content, Status, PublishedAt, ViewCount, AI fields |
| **User** | Kullanıcı | UserName, Email, PasswordHash, Role, LockoutEndTime |
| **Category** | Kategori | Name, Slug, Description |
| **Tag** | Etiket | Name, Slug |
| **Comment** | Yorum | Content, AuthorId, PostId |
| **RefreshToken** | Refresh token | Token, ExpiresAt, RevokedAt |

#### Value Objects
```csharp
// ValueObjects/Email.cs
public sealed partial record Email
{
    public string Value { get; }

    public static Email Create(string email)
    {
        if (string.IsNullOrWhiteSpace(email))
            throw new DomainException("Email cannot be empty");

        email = email.Trim().ToLowerInvariant();

        if (!EmailRegex().IsMatch(email))
            throw new DomainException("Invalid email format");

        return new Email(email);
    }

    [GeneratedRegex(@"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")]
    private static partial Regex EmailRegex();
}
```

#### Enums
```csharp
public enum PostStatus
{
    Draft = 0,
    Published = 1,
    Archived = 2
}

public enum UserRole
{
    Reader = 0,
    Author = 1,
    Editor = 2,
    Admin = 3
}
```

### 3.8 AI-Enhanced BlogPost Entity

```csharp
public class BlogPost : BaseAuditableEntity
{
    // Standart alanlar
    public string Title { get; set; }
    public string Slug { get; set; }
    public string Content { get; set; }
    public string? Excerpt { get; set; }
    public PostStatus Status { get; set; }

    // AI-Generated alanlar
    public string? AiSummary { get; set; }                  // RAG-based summary
    public string? AiKeywords { get; set; }                 // Extracted keywords
    public int? AiEstimatedReadingTime { get; set; }        // AI-calculated reading time
    public string? AiSeoDescription { get; set; }           // SEO meta description
    public DateTime? AiProcessedAt { get; set; }            // Processing timestamp
    public string? AiGeoOptimization { get; set; }          // JSON-serialized GEO data

    // Domain Methods
    public void Publish()
    {
        Status = PostStatus.Published;
        PublishedAt = DateTime.UtcNow;
    }

    public void Archive()
    {
        Status = PostStatus.Archived;
    }
}
```

### 3.9 Caching Stratejisi

#### İki Katmanlı Hibrit Cache (L1+L2)

```
┌─────────────────────────────────────────────────────────┐
│                   CacheService                          │
│         (Implements ICacheService)                      │
│  - L1: IMemoryCache (in-memory)                        │
│  - L2: IDistributedCache (Redis)                       │
│  - SWR: Stale-While-Revalidate support                 │
└─────────────────────────────────────────────────────────┘
```

**Cache Özellikleri:**
- **L1 (Local Memory)**: Hızlı in-memory cache (instance başına)
- **L2 (Redis)**: Paylaşılan distributed cache
- **SWR (Stale-While-Revalidate)**: Eski veriyi hemen göster, arka planda güncelle

#### Cache Behavior
```csharp
public class CachingBehavior<TRequest, TResponse>
    : IPipelineBehavior<TRequest, TResponse>
    where TRequest : ICacheableQuery
{
    public async Task<TResponse> Handle(
        TRequest request,
        RequestHandlerDelegate<TResponse> next,
        CancellationToken ct)
    {
        // 1. Cache key oluştur
        var cacheKey = GenerateCacheKey(request);

        // 2. SWR kontrolü
        if (request.UseStaleWhileRevalidate)
        {
            return await GetWithStaleWhileRevalidate(cacheKey, next, ct);
        }

        // 3. Standart cache
        return await GetOrCreate(cacheKey, next, ct);
    }
}
```

### 3.10 Authentication/Authorization

#### JWT Implementation
```csharp
// JwtTokenService.cs
public class JwtTokenService : IJwtTokenService
{
    public string GenerateAccessToken(User user)
    {
        var claims = new[]
        {
            new Claim(JwtRegisteredClaimNames.Sub, user.Id.ToString()),
            new Claim(JwtRegisteredClaimNames.Email, user.Email.Value),
            new Claim("name", user.FullName),
            new Claim(ClaimTypes.Role, user.Role.ToString())
        };

        var token = new JwtSecurityToken(
            issuer: _jwtSettings.Issuer,
            audience: _jwtSettings.Audience,
            claims: claims,
            expires: DateTime.UtcNow.AddMinutes(60),  // 60 dakika
            signingCredentials: credentials
        );

        return new JwtSecurityTokenHandler().WriteToken(token);
    }
}
```

#### Refresh Token Flow
```
┌─────────────┐      1. Login Request       ┌─────────────┐
│   Client    │ ──────────────────────────► │   Backend   │
└─────────────┘                              └─────────────┘
      ▲                                                │
      │                                                │
      │ 2. Access Token + Refresh Token (HttpOnly)    │
      │                                                │
      │                                                ▼
┌─────────────┐   3. API Request with Token   ┌─────────────┐
│   Client    │ ──────────────────────────► │   Backend   │
└─────────────┘                              └─────────────┘
      ▲                                                │
      │                                                │
      │ 4. 401 Unauthorized                           │
      │                                                │
      │                                                ▼
┌─────────────┐   5. Refresh Token Request   ┌─────────────┐
│   Client    │ ──────────────────────────► │   Backend   │
└─────────────┘                              └─────────────┘
      ▲                                                │
      │                                                │
      │ 6. New Access Token                           │
      │                                                │
      └────────────────────────────────────────────────┘
```

#### Account Lockout
```csharp
// User entity
public class User
{
    public int FailedLoginAttempts { get; set; } = 0;
    public DateTime? LockoutEndTime { get; set; }

    public void RecordFailedLogin()
    {
        FailedLoginAttempts++;
        if (FailedLoginAttempts >= 5)
        {
            LockoutEndTime = DateTime.UtcNow.AddMinutes(30);
        }
    }

    public bool IsLockedOut()
    {
        return LockoutEndTime.HasValue && LockoutEndTime.Value > DateTime.UtcNow;
    }
}
```

### 3.11 API Endpoints

#### Minimal API Structure
```csharp
// Endpoints/PostsEndpoints.cs
var group = app.MapGroup("/api/v1/posts")
    .WithTags("Posts")
    .WithOpenApi()
    .RequireAuthorization();

group.MapGet("/", async (IMediator mediator, CancellationToken ct) =>
{
    var response = await mediator.Send(new GetPostsListQueryRequest(), ct);
    return Results.Ok(response);
})
.WithName("GetAllPosts")
.CacheOutput("PostsList")
.Produces<ApiResponse<PaginatedList<PostListQueryDto>>>(200);
```

#### Endpoint Groups
| Group | Base Path | Endpoints |
|-------|-----------|-----------|
| **AuthEndpoints** | `/api/v1/auth` | login, register, refresh-token, logout, me |
| **PostsEndpoints** | `/api/v1/posts` | CRUD, publish, drafts, AI analysis |
| **CategoriesEndpoints** | `/api/v1/categories` | CRUD |
| **TagsEndpoints** | `/api/v1/tags` | CRUD |
| **MediaEndpoints** | `/api/v1/media` | Image upload |
| **AiEndpoints** | `/api/v1/ai` | AI content generation |
| **ChatEndpoints** | `/api/v1/chat` | Article chat (RAG) |

### 3.12 Business Rules Engine

```csharp
// Common/BusinessRuleEngine/BusinessRuleEngine.cs
public class BusinessRuleEngine
{
    public static Result Run(params Result[] rules)
    {
        foreach (var rule in rules)
        {
            if (!rule.IsSuccess)
                return rule;
        }
        return Result.Success();
    }

    public static async Task<Result> RunAsync(params Func<Task<Result>>[] rules)
    {
        foreach (var rule in rules)
        {
            var result = await rule();
            if (!result.IsSuccess)
                return result;
        }
        return Result.Success();
    }
}
```

**Örnek Kullanım:**
```csharp
// PostBusinessRules.cs
public class PostBusinessRules : IPostBusinessRules
{
    public async Task<Result> PostShouldExist(Guid postId)
    {
        var post = await _unitOfWork.PostsRead.GetByIdAsync(postId);
        return post is null
            ? Result.Failure("Post not found")
            : Result.Success();
    }

    public async Task<Result> PostSlugShouldBeUnique(string slug)
    {
        var exists = await _unitOfWork.PostsRead.ExistsAsync(p => p.Slug == slug);
        return exists
            ? Result.Failure("A post with this slug already exists")
            : Result.Success();
    }
}

// Handler içinde kullanımı
var result = await BusinessRuleEngine.RunAsync(
    () => _postBusinessRules.PostShouldExist(request.Id),
    () => _postBusinessRules.PostSlugShouldBeUnique(request.Slug)
);

if (!result.IsSuccess)
    return Result.Failure<Post>(result.Error);
```

### 3.13 Middleware Pipeline

```csharp
// Program.cs - Middleware sırası
var app = builder.Build();

app.UseForwardedHeaders();           // 1. Proxy headers
app.UseSecurityHeaders();             // 2. Custom security headers
app.UseExceptionHandling();           // 3. Global exception handler
app.UseRequestLogging();              // 4. Request/response logging
app.UseResponseCompression();         // 5. Brotli/Gzip compression
app.UseHttpsRedirection();            // 6. HTTPS redirect (dev only)
app.UseStaticFiles();                 // 7. Static files (/uploads)
app.UseCors();                        // 8. CORS policy
app.UseIpRateLimiting();              // 9. Rate limiting
app.UseAuthentication();              // 10. JWT authentication
app.UseAuthorization();               // 11. Authorization policies
app.UseOutputCache();                 // 12. HTTP output caching
app.UseAntiforgery();                 // 13. CSRF protection
app.MapEndpoints();                   // 14. Minimal API routes
app.MapHub<CacheInvalidationHub>("/hubs/cache");  // 15. SignalR
app.MapPrometheusScrapingEndpoint();  // 16. Metrics (/metrics)
```

### 3.14 Data Layer

#### Entity Framework Core
```csharp
// Persistence/AppDbContext.cs
public class AppDbContext : DbContext, IApplicationDbContext
{
    public DbSet<BlogPost> Posts { get; }
    public DbSet<Category> Categories { get; }
    public DbSet<Tag> Tags { get; }
    public DbSet<User> Users { get; }
    public DbSet<Comment> Comments { get; }
    public DbSet<RefreshToken> RefreshTokens { get; }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.ApplyConfigurationsFromAssembly(Assembly.GetExecutingAssembly());

        // Global query filters for soft delete
        modelBuilder.Entity<BlogPost>().HasQueryFilter(p => !p.IsDeleted);
        modelBuilder.Entity<Category>().HasQueryFilter(c => !c.IsDeleted);
    }
}
```

#### Migrations
| Migration | Açıklama |
|-----------|----------|
| `20251227031847_InitialCreate` | İlk schema oluşturma |
| `20260101130937_AddSearchVector` | PostgreSQL full-text search (tsvector) |
| `20260104125311_AddPartialUniqueIndexes` | Performans indexleri |
| `20260114202204_AddAiFields` | AI analysis alanları |
| `20260118002635_AddAiGeoOptimizationField` | GEO optimization JSON field |

---

## 4. Building Blocks (Paylaşılan Bileşenler)

### 4.1 Mimari

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BlogApp.BuildingBlocks                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Building Blocks Pattern (Vertical Slice Architecture)        │  │
│  │                                                               │  │
│  │  ┌─────────────────────────────┐  ┌─────────────────────────┐ │  │
│  │  │   Caching Building Block    │  │  Messaging Building Block│ │  │
│  │  │  - IBasicCacheService       │  │  - IEventBus            │  │  │
│  │  │  - IHybridCacheService      │  │  - IIntegrationEvent    │  │
│  │  │  - Redis Implementation     │  │  - RabbitMQ             │  │
│  │  │  - L1/L2 Hybrid Cache       │  │  - Event Consumer       │  │  │
│  │  └─────────────────────────────┘  └─────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Caching Building Block

#### Abstractions
```csharp
// IBasicCacheService.cs
public interface IBasicCacheService
{
    Task<T?> GetAsync<T>(string key, CancellationToken cancellationToken = default);
    Task SetAsync<T>(string key, T value, TimeSpan? expiration = null, CancellationToken cancellationToken = default);
    Task RemoveAsync(string key, CancellationToken cancellationToken = default);
    Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default);
    Task<T> GetOrSetAsync<T>(string key, Func<Task<T>> factory, TimeSpan? expiration = null, CancellationToken cancellationToken = default);
}
```

```csharp
// IHybridCacheService.cs
public interface IHybridCacheService
{
    // L1: In-memory cache (ultra hızlı)
    // L2: Distributed cache (Redis)

    Task<T?> GetAsync<T>(string key, CancellationToken cancellationToken = default);
    Task SetAsync<T>(string key, T value, TimeSpan? l1Expiration, TimeSpan? l2Expiration, CancellationToken cancellationToken = default);
    Task RemoveAsync(string key, CancellationToken cancellationToken = default);
    Task RemoveByPrefixAsync(string prefix, CancellationToken cancellationToken = default);

    // Cache group versioning
    Task InvalidateGroupAsync(string groupName, CancellationToken cancellationToken = default);

    // Stale-While-Revalidate
    Task<T> GetOrSetAsync<T>(
        string key,
        Func<Task<T>> factory,
        TimeSpan? l1Expiration,
        TimeSpan? l2Expiration,
        bool useStaleWhileRevalidate = false,
        double swrSoftRatio = 0.5,
        CancellationToken cancellationToken = default
    );
}
```

#### Implementation
```csharp
// Redis/BasicRedisCacheService.cs
public class BasicRedisCacheService : IBasicCacheService
{
    private readonly IDistributedCache _cache;
    private readonly JsonSerializerOptions _jsonOptions;

    public async Task<T?> GetAsync<T>(string key, CancellationToken ct)
    {
        var json = await _cache.GetStringAsync(key, ct);
        return json is null ? default : JsonSerializer.Deserialize<T>(json, _jsonOptions);
    }

    public async Task SetAsync<T>(string key, T value, TimeSpan? expiration, CancellationToken ct)
    {
        var json = JsonSerializer.Serialize(value, _jsonOptions);
        await _cache.SetStringAsync(key, json, new DistributedCacheEntryOptions
        {
            AbsoluteExpirationRelativeToNow = expiration
        }, ct);
    }
}
```

#### Configuration
```json
{
  "Redis": {
    "ConnectionString": "localhost:6379",
    "Enabled": true,
    "InstanceName": "BlogApp:",
    "DefaultExpirationMinutes": 30
  }
}
```

#### Dependency Injection
```csharp
// DependencyInjection.cs
public static IServiceCollection AddBasicCachingServices(
    this IServiceCollection services,
    IConfiguration configuration)
{
    var redisSettings = configuration.GetSection("Redis").Get<RedisSettings>();

    if (redisSettings.Enabled)
    {
        services.AddStackExchangeRedisCache(options =>
        {
            options.Configuration = redisSettings.ConnectionString;
            options.InstanceName = redisSettings.InstanceName;
        });
    }
    else
    {
        services.AddDistributedMemoryCache();
    }

    services.AddSingleton<IBasicCacheService, BasicRedisCacheService>();

    return services;
}

public static IServiceCollection AddHybridCachingInfrastructure(
    this IServiceCollection services,
    IConfiguration configuration)
{
    // L1: IMemoryCache (built-in)
    services.AddMemoryCache();

    // L2: Redis or DistributedMemoryCache
    services.AddBasicCachingServices(configuration);

    // Hybrid implementation
    services.AddSingleton<IHybridCacheService, HybridCacheService>();

    return services;
}
```

### 4.3 Messaging Building Block

#### Abstractions
```csharp
// IEventBus.cs
public interface IEventBus
{
    Task PublishAsync<TEvent>(TEvent @event, string routingKey, CancellationToken cancellationToken = default)
        where TEvent : IIntegrationEvent;
    bool IsConnected { get; }
}

// IIntegrationEvent.cs
public interface IIntegrationEvent
{
    string MessageId { get; }
    string CorrelationId { get; }
    DateTime Timestamp { get; }
    string EventType { get; }
}
```

#### AI Event Definitions
```csharp
// Events/AiEvents.cs
public record AiTitleGenerationRequestedEvent : IIntegrationEvent
{
    public string MessageId => Guid.NewGuid().ToString();
    public string CorrelationId { get; init; } = Guid.NewGuid().ToString();
    public DateTime Timestamp => DateTime.UtcNow;
    public string EventType => "ai.title.generation.requested";

    public required string Content { get; init; }
    public required string Language { get; init; }
}

public record AiExcerptGenerationRequestedEvent : IIntegrationEvent
{
    public string MessageId => Guid.NewGuid().ToString();
    public string CorrelationId { get; init; } = Guid.NewGuid().ToString();
    public DateTime Timestamp => DateTime.UtcNow;
    public string EventType => "ai.excerpt.generation.requested";

    public required string Content { get; init; }
    public int MaxLength { get; init; } = 160;
}

public record AiTagsGenerationRequestedEvent : IIntegrationEvent
{
    public string MessageId => Guid.NewGuid().ToString();
    public string CorrelationId { get; init; } = Guid.NewGuid().ToString();
    public DateTime Timestamp => DateTime.UtcNow;
    public string EventType => "ai.tags.generation.requested";

    public required string Content { get; init; }
    public int MaxTags { get; init; } = 5;
}

public record AiSeoDescriptionGenerationRequestedEvent : IIntegrationEvent
{
    public string MessageId => Guid.NewGuid().ToString();
    public string CorrelationId { get; init; } = Guid.NewGuid().ToString();
    public DateTime Timestamp => DateTime.UtcNow;
    public string EventType => "ai.seo.generation.requested";

    public required string Content { get; init; }
    public required string Keywords { get; init; }
    public int MaxLength { get; init; } = 160;
}

public record AiContentImprovementRequestedEvent : IIntegrationEvent
{
    public string MessageId => Guid.NewGuid().ToString();
    public string CorrelationId { get; init; } = Guid.NewGuid().ToString();
    public DateTime Timestamp => DateTime.UtcNow;
    public string EventType => "ai.content.improvement.requested";

    public required string Content { get; init; }
    public required string FocusArea { get; init; }  // readability, seo, engagement
}
```

#### Implementation
```csharp
// RabbitMQ/RabbitMqEventBus.cs
public class RabbitMqEventBus : IEventBus
{
    private readonly IModel _channel;
    private readonly RabbitMqSettings _settings;
    private readonly string _exchangeName = "blog.events";

    public async Task PublishAsync<TEvent>(TEvent @event, string routingKey, CancellationToken ct)
    where TEvent : IIntegrationEvent
    {
        if (!_settings.Enabled)
            return;

        var message = JsonSerializer.Serialize(@event);
        var body = Encoding.UTF8.GetBytes(message);

        var properties = _channel.CreateBasicProperties();
        properties.DeliveryMode = 2;  // Persistent
        properties.MessageId = @event.MessageId;
        properties.CorrelationId = @event.CorrelationId;
        properties.ContentType = "application/json";
        properties.Timestamp = new AmqpTimestamp(@event.Timestamp.Ticks);

        _channel.BasicPublish(
            exchange: _exchangeName,
            routingKey: routingKey,
            basicProperties: properties,
            body: body
        );
    }

    public bool IsConnected => _channel.IsOpen;
}
```

#### Configuration
```json
{
  "RabbitMQ": {
    "HostName": "localhost",
    "Port": 5672,
    "UserName": "admin",
    "Password": "your_secure_password",
    "VirtualHost": "/",
    "Enabled": false
  }
}
```

#### Dependency Injection
```csharp
// DependencyInjection.cs
public static IServiceCollection AddMessagingServices(
    this IServiceCollection services,
    IConfiguration configuration)
{
    var settings = configuration.GetSection("RabbitMQ").Get<RabbitMqSettings>();

    if (settings.Enabled)
    {
        services.AddSingleton<RabbitMqConnection>();
        services.AddSingleton<IEventBus, RabbitMqEventBus>();

        // Event consumer
        services.AddSingleton<RabbitMqEventConsumer>();
        services.AddHostedService(sp => sp.GetRequiredService<RabbitMqEventConsumer>());
    }
    else
    {
        // No-op implementation
        services.AddSingleton<IEventBus, NoOpEventBus>();
    }

    return services;
}
```

---

## 5. AI Agent Service

### 5.1 Teknoloji Stack

**Language:** Python 3.12

**Core Frameworks:**
- **FastAPI** (0.115.0) - Async web framework
- **Uvicorn** (0.32.0) - ASGI server
- **Pydantic** (2.10.0) - Data validation

**AI/LLM Stack:**
- **LangChain** (0.3.7) - LLM orchestration
- **LangChain-Ollama** (0.1.0) - Ollama integration
- **Ollama** - Local LLM server (gemma3:8b)

**Vector Store & RAG:**
- **ChromaDB** (0.4.22) - Vector database
- **sentence-transformers** (2.2.2) - Embeddings
- **rank-bm25** (0.2.2) - BM25 search

**Messaging:**
- **aio-pika** (9.4.0) - Async AMQP (RabbitMQ)

**Caching:**
- **Redis** (5.2.0) - Distributed cache
- **cachetools** (5.3.0) - In-memory cache

**Web Search:**
- **ddgs** (1.0.0) - DuckDuckGo search

**Utilities:**
- **httpx** (0.28.0) - Async HTTP
- **slowapi** (0.1.9) - Rate limiting
- **tenacity** (9.0.0) - Retry logic

### 5.2 Mimari

```
┌─────────────────────────────────────────────────────────────────────┐
│                      AI Agent Service (Python)                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                      FastAPI Application                      │  │
│  │  /api/analyze | /api/chat/stream | /api/summarize | ...      │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                        │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                Hexagonal Architecture                         │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐  │  │
│  │  │    Domain       │  │    Services     │  │Infrastructure│  │  │
│  │  │  - Entities     │  │  - Analysis     │  │- Ollama LLM  │  │  │
│  │  │  - Interfaces   │  │  - Chat (RAG)   │  │- ChromaDB    │  │  │
│  │  │                 │  │  - SEO          │  │- Redis       │  │  │
│  │  │                 │  │  - Indexing     │  │- RabbitMQ    │  │  │
│  │  └─────────────────┘  └─────────────────┘  └──────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                        │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                      Message Processor                        │  │
│  │  - Idempotency (Redis)                                       │  │
│  │  - Distributed Locks                                         │  │
│  │  - Event Processing (article, ai.*, chat)                    │  │
│  │  - Result Publishing (RabbitMQ)                              │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.3 LLM Provider Interface (Hexagonal Architecture)

```python
# infrastructure/llm/ollama_adapter.py
class OllamaAdapter(ILLMProvider):
    def __init__(
        self,
        model: str = "gemma3:8b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.7,
        timeout: int = 120,
        num_ctx: int = 128000
    ):
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.timeout = timeout
        self.num_ctx = num_ctx

    async def generate_text(self, prompt: str) -> str:
        """Generate text from prompt."""
        response = await ollama.AsyncClient(
            host=self.base_url
        ).generate(
            model=self.model,
            prompt=prompt,
            options={
                "temperature": self.temperature,
                "num_ctx": self.num_ctx
            }
        )
        return response['response']

    async def generate_json(self, prompt: str) -> dict:
        """Generate JSON response from prompt."""
        json_prompt = f"{prompt}\n\nRespond only with valid JSON."
        response = await self.generate_text(json_prompt)
        return json.loads(response)

    async def warmup(self) -> None:
        """Warmup the model by sending a test request."""
        await self.generate_text("Hello")
```

### 5.4 AI Services

#### AnalysisService
```python
# services/analysis_service.py
class AnalysisService:
    def __init__(self, llm: ILLMProvider, cache: ICacheService):
        self.llm = llm
        self.cache = cache

    async def summarize(self, content: str, language: str = "tr") -> str:
        """Generate 3-sentence summary."""
        prompt = f"""
        Summarize the following content in 3 sentences in {language}:

        {content}
        """
        cache_key = f"summary:{hash(content)}:{language}"
        return await self.cache.get_or_set(cache_key, lambda: self.llm.generate_text(prompt))

    async def extract_keywords(self, content: str, top_n: int = 5) -> list[str]:
        """Extract top N keywords."""
        prompt = f"""
        Extract the top {top_n} keywords from the following content.
        Respond only with a comma-separated list of keywords.

        Content: {content}
        """
        response = await self.llm.generate_text(prompt)
        return [k.strip() for k in response.split(",")]

    async def analyze_sentiment(self, content: str) -> dict:
        """Analyze sentiment (positive/negative/neutral) with confidence."""
        prompt = f"""
        Analyze the sentiment of the following content.
        Respond with JSON: {{"sentiment": "positive|negative|neutral", "confidence": 0.0-1.0}}

        Content: {content}
        """
        return await self.llm.generate_json(prompt)

    async def calculate_reading_time(self, content: str, words_per_minute: int = 200) -> int:
        """Calculate estimated reading time in minutes."""
        word_count = len(content.split())
        return max(1, math.ceil(word_count / words_per_minute))

    async def full_analysis(self, content: str, language: str = "tr") -> dict:
        """Run all analysis in parallel."""
        summary, keywords, sentiment, reading_time = await asyncio.gather(
            self.summarize(content, language),
            self.extract_keywords(content),
            self.analyze_sentiment(content),
            self.calculate_reading_time(content)
        )

        return {
            "summary": summary,
            "keywords": keywords,
            "sentiment": sentiment,
            "reading_time": reading_time
        }
```

#### ChatService (RAG-powered Q&A)
```python
# services/chat_service.py
class ChatService:
    def __init__(
        self,
        llm: ILLMProvider,
        vector_store: IVectorStore,
        web_search: IWebSearch
    ):
        self.llm = llm
        self.vector_store = vector_store
        self.web_search = web_search

    async def chat(
        self,
        question: str,
        article_id: str,
        agent_type: str = "normal"
    ) -> AsyncIterator[str]:
        """Stream chat response."""

        # 1. Retrieve relevant context from vector store
        relevant_docs = await self.vector_store.search(
            query=question,
            collection_name="blog_articles",
            n_results=3,
            filter={"article_id": article_id}
        )

        context = "\n\n".join([doc["content"] for doc in relevant_docs])

        # 2. Build RAG prompt
        if agent_type == "web-search":
            # Hybrid: RAG + Web search
            web_sources = await self.web_search.search(question, n_results=3)
            web_context = "\n\n".join([s["content"] for s in web_sources])

            prompt = f"""
            Answer the question using the following context from the article and web sources.

            Article Context:
            {context}

            Web Sources:
            {web_context}

            Question: {question}

            Provide a comprehensive answer with citations.
            """
        else:
            # RAG only
            prompt = f"""
            You are a helpful assistant answering questions about a blog article.

            Article Context:
            {context}

            Question: {question}

            Answer the question based on the article context.
            If the context doesn't contain the answer, say "I don't have enough information to answer this."
            """

        # 3. Stream LLM response
        async for chunk in self.llm.stream_text(prompt):
            yield chunk

    async def validate_relevance(self, question: str, answer: str) -> bool:
        """Validate that the answer is relevant to the question (multi-signal)."""

        # Signal 1: LLM semantic check
        validation_prompt = f"""
        Question: {question}
        Answer: {answer}

        Does the answer directly address the question? Respond with "yes" or "no".
        """
        llm_response = await self.llm.generate_text(validation_prompt)
        if "no" in llm_response.lower():
            return False

        # Signal 2: Answer length check
        if len(answer.split()) < 20:
            return False

        # Signal 3: Keyword overlap
        question_keywords = set(question.lower().split())
        answer_keywords = set(answer.lower().split())
        overlap = len(question_keywords & answer_keywords) / len(question_keywords)
        if overlap < 0.2:
            return False

        return True
```

#### SeoService
```python
# services/seo_service.py
class SeoService:
    def __init__(self, llm: ILLMProvider):
        self.llm = llm

    async def generate_seo_description(
        self,
        content: str,
        keywords: list[str],
        max_length: int = 160
    ) -> str:
        """Generate SEO meta description."""
        prompt = f"""
        Create an SEO-optimized meta description for the following content.
        Include these keywords: {', '.join(keywords)}
        Maximum {max_length} characters.

        Content: {content}
        """
        description = await self.llm.generate_text(prompt)
        return description[:max_length]

    async def optimize_for_geo(
        self,
        content: str,
        target_region: str,
        language: str = "tr"
    ) -> dict:
        """Optimize content for specific region (GEO optimization)."""
        prompt = f"""
        Optimize the following content for {target_region} region in {language} language.
        Consider:
        - Local cultural references
        - Regional keywords
        - Local search trends

        Respond with JSON:
        {{
            "optimized_content": "...",
            "suggested_keywords": ["..."],
            "cultural_notes": "..."
        }}

        Content: {content}
        """
        return await self.llm.generate_json(prompt)
```

### 5.5 API Endpoints

#### Analysis Endpoints
```python
# api/v1/endpoints/analysis.py
@router.post("/api/summarize")
@rate_limit(20)  # 20 requests per minute
async def summarize(request: SummarizeRequest):
    """Generate article summary."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{AI_SERVICE_URL}/api/summarize",
            json=request.dict(),
            headers={"X-API-Key": settings.ai_service_api_key}
        )
    return response.json()

@router.post("/api/keywords")
@rate_limit(30)  # 30 requests per minute
async def extract_keywords(request: KeywordsRequest):
    """Extract keywords from content."""
    # Similar to summarize
    pass

@router.post("/api/seo-description")
@rate_limit(20)
async def generate_seo_description(request: SeoDescriptionRequest):
    """Generate SEO meta description."""
    pass

@router.post("/api/analyze")
@rate_limit(10)  # 10 requests per minute (most expensive)
async def full_analysis(request: AnalysisRequest):
    """Full article analysis (summary, keywords, SEO, sentiment, GEO)."""
    pass
```

#### Chat Endpoints
```python
# api/v1/endpoints/chat.py
@router.post("/api/stream")
@rate_limit(60)
async def stream_chat(request: ChatRequest):
    """Stream chat response via Server-Sent Events."""

    async def event_stream():
        async for chunk in chat_service.chat(
            question=request.question,
            article_id=request.article_id,
            agent_type=request.agent_type
        ):
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.post("/api/collect-sources")
@rate_limit(20)
async def collect_sources(request: CollectSourcesRequest):
    """Collect web sources for article."""
    sources = await web_search.search(
        query=request.query,
        n_results=5
    )
    return {"sources": sources}
```

### 5.6 Messaging Integration (RabbitMQ)

#### Consumer Implementation
```python
# messaging/consumer.py
class AiMessageConsumer:
    def __init__(
        self,
        connection: aio_pika.RobustConnection,
        processor: MessageProcessor
    ):
        self.connection = connection
        self.processor = processor
        self.channel = None
        self.queue = None

    async def start(self):
        """Start consuming messages."""
        self.channel = await self.connection.channel()
        await self.channel.set_qos(prefetch_count=1)  # Backpressure control

        # Declare exchange
        exchange = await self.channel.declare_exchange(
            "blog.events",
            aio_pika.ExchangeType.DIRECT,
            durable=True
        )

        # Declare queue (quorum queue for durability)
        self.queue = await self.channel.declare_queue(
            "q.ai.analysis",
            durable=True,
            arguments={"x-queue-type": "quorum"}
        )

        # Bind routing keys
        routing_keys = [
            "article.created",
            "article.published",
            "article.updated",
            "ai.analysis.requested",
            "ai.title.generation.requested",
            "ai.excerpt.generation.requested",
            "ai.tags.generation.requested",
            "ai.seo.generation.requested",
            "ai.content.improvement.requested",
            "chat.message.requested"
        ]

        for routing_key in routing_keys:
            await self.queue.bind(exchange, routing_key=routing_key)

        # Start consuming
        async with self.queue.iterator() as queue_iter:
            async for message in queue_iter:
                await self.process_message(message)

    async def process_message(self, message: aio_pika.IncomingMessage):
        """Process a single message."""
        async with message.process():
            try:
                event_data = json.loads(message.body.decode())
                await self.processor.process(event_data, message.routing_key)
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                # NACK with requeue=False (send to DLQ)
                await message.nack(requeue=False)
```

#### Message Processor
```python
# messaging/processor.py
class MessageProcessor:
    def __init__(
        self,
        redis: Redis,
        analysis_service: AnalysisService,
        chat_service: ChatService,
        event_bus: RabbitMqEventBus
    ):
        self.redis = redis
        self.analysis_service = analysis_service
        self.chat_service = chat_service
        self.event_bus = event_bus

    async def process(self, event_data: dict, routing_key: str):
        """Process event by type."""

        message_id = event_data.get("messageId") or event_data.get("MessageId")

        # 1. Idempotency check
        if await self.redis.exists(f"processed:{message_id}"):
            logger.info(f"Message {message_id} already processed, skipping")
            return

        # 2. Acquire distributed lock
        entity_id = event_data.get("articleId") or event_data.get("ArticleId") or message_id
        lock_key = f"lock:{entity_id}"

        lock = await self.redis.set(lock_key, "1", nx=True, ex=30)
        if not lock:
            logger.warning(f"Could not acquire lock for {entity_id}")
            return

        try:
            # 3. Process by routing key
            if routing_key.startswith("article."):
                await self.process_article(event_data)
            elif routing_key.startswith("ai."):
                await self.process_ai_request(event_data)
            elif routing_key == "chat.message.requested":
                await self.process_chat_request(event_data)

            # 4. Mark as processed
            await self.redis.setex(f"processed:{message_id}", 86400, "1")  # 24 hours

        finally:
            # 5. Release lock
            await self.redis.delete(lock_key)

    async def process_article(self, event_data: dict):
        """Process article event (run full analysis + index for RAG)."""
        article_id = event_data["articleId"]
        content = event_data["content"]
        title = event_data["title"]

        # Run full analysis
        analysis = await self.analysis_service.full_analysis(content)

        # Index for RAG
        await vector_store.add_document(
            collection_name="blog_articles",
            document_id=article_id,
            text=content,
            metadata={"title": title, "article_id": article_id}
        )

        # Publish completion event
        await self.event_bus.publish(
            AiAnalysisCompletedEvent(
                article_id=article_id,
                summary=analysis["summary"],
                keywords=analysis["keywords"],
                sentiment=analysis["sentiment"],
                reading_time=analysis["reading_time"]
            ),
            routing_key="ai.analysis.completed"
        )

    async def process_ai_request(self, event_data: dict):
        """Process AI generation request."""
        request_type = event_data["requestType"]  # title, excerpt, tags, seo, improvement
        content = event_data["content"]

        result = None
        routing_key = None

        if request_type == "title":
            result = await self.analysis_service.generate_title(content)
            routing_key = "ai.title.completed"
        elif request_type == "excerpt":
            result = await self.analysis_service.summarize(content)
            routing_key = "ai.excerpt.completed"
        # ... etc

        # Publish result
        await self.event_bus.publish(
            AiGenerationCompletedEvent(result=result),
            routing_key=routing_key
        )
```

### 5.7 Configuration

#### Environment Variables
```bash
# .env.example

# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:8b
OLLAMA_TIMEOUT=120
OLLAMA_NUM_CTX=128000
OLLAMA_TEMPERATURE=0.7

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# RabbitMQ Configuration
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=admin
RABBITMQ_PASS=your_secure_password
RABBITMQ_VHOST=/

# Backend API Configuration
BACKEND_API_URL=http://localhost:5116/api/v1

# Server Settings
HOST=0.0.0.0
PORT=8000
DEBUG=false

# API Key for rate limiting
AI_SERVICE_API_KEY=your_secure_api_key_here
```

### 5.8 Docker Configuration

```dockerfile
# Dockerfile
FROM python:3.12-slim as base

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ./app ./app

# Create non-root user
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 6. Teknoloji Stack Özeti

### 6.1 Frontend
| Kategori | Teknoloji | Sürüm | Amaç |
|----------|----------|-------|------|
| **Framework** | Next.js | 16.1.1 | React framework with SSR/ISR |
| **UI Library** | React | 19.2.3 | UI library |
| **Language** | TypeScript | 5.x | Type-safe JavaScript |
| **Styling** | TailwindCSS | 4.x | Utility-first CSS |
| **UI Components** | shadcn/ui | latest | Accessible component library |
| **State Management** | Zustand | 5.0.9 | Lightweight state management |
| **HTTP Client** | Axios | 1.13.2 | HTTP requests |
| **Real-time** | SignalR | 10.0.0 | WebSocket communication |
| **Markdown** | react-markdown | 10.1.0 | Markdown rendering |
| **Forms** | react-hook-form | 7.69.0 | Form management |
| **Validation** | Zod | 4.2.1 | Schema validation |

### 6.2 Backend
| Kategori | Teknoloji | Sürüm | Amaç |
|----------|----------|-------|------|
| **Framework** | .NET | 10.0 | Server-side framework |
| **Language** | C# | 12.0 | Programming language |
| **ORM** | Entity Framework Core | 10.0.1 | Database ORM |
| **Database** | PostgreSQL | 16.x | Relational database |
| **CQRS** | MediatR | 14.0.0 | CQRS/Mediator pattern |
| **Validation** | FluentValidation | 12.1.1 | Request validation |
| **Mapping** | AutoMapper | 16.0.0 | Object mapping |
| **Authentication** | JWT | - | Token-based auth |
| **Cache** | Redis | 7.x | Distributed cache |
| **Messaging** | RabbitMQ | 3.12.x | Event-driven messaging |
| **Real-time** | SignalR | 10.0.0 | WebSocket framework |
| **Logging** | Serilog | 10.0.0 | Structured logging |
| **Documentation** | Swagger/OpenAPI | 10.1.0 | API documentation |
| **Rate Limiting** | AspNetCoreRateLimit | 5.0.0 | Rate limiting |
| **Metrics** | OpenTelemetry | 1.14.0 | Observability |

### 6.3 AI Service
| Kategori | Teknoloji | Sürüm | Amaç |
|----------|----------|-------|------|
| **Framework** | FastAPI | 0.115.0 | Async web framework |
| **Language** | Python | 3.12 | Programming language |
| **LLM** | Ollama | latest | Local LLM server |
| **Model** | gemma3 | 8b | LLM model |
| **Vector Store** | ChromaDB | 0.4.22 | Vector embeddings |
| **Embeddings** | sentence-transformers | 2.2.2 | Text embeddings |
| **RAG** | LangChain | 0.3.7 | LLM orchestration |
| **Messaging** | aio-pika | 9.4.0 | RabbitMQ client |
| **Cache** | Redis | 5.2.0 | Distributed cache |
| **Web Search** | ddgs | 1.0.0 | DuckDuckGo search |
| **Rate Limiting** | slowapi | 0.1.9 | Rate limiting |

---

## 7. Veri Akışı Diyagramları

### 7.1 Login Flow
```
┌──────────┐          1. POST /api/v1/auth/login          ┌──────────────┐
│  Client  │ ──────────────────────────────────────────► │   Backend    │
│ (Next.js)│                                          │    (.NET)     │
└──────────┘                                          └──────┬───────┘
      ▲                                                      │
      │                                                      │
      │  2. Validate credentials (BCrypt)                   │
      │                                                      │
      │                                                      ▼
      │                                              ┌──────────────┐
      │                                              │ PostgreSQL   │
      │                                              │   Database   │
      │                                              └──────┬───────┘
      │                                                     │
      │                                                     │
      │  3. User found                                      │
      │                                                     │
      │  4. Generate JWT + Refresh Token                   │
      │                                                     │
      │                                                     │
      └─────────────────────────────────────────────────────┘
      │
      │  5. Set HttpOnly cookies
      │     - BlogApp.AccessToken (JWT, 60min)
      │     - BlogApp.RefreshToken (30 days)
      │
      │  6. Return { user, accessToken }
      │
      ▼
┌──────────┐
│  Client  │  Store user in Zustand (persist)
└──────────┘
```

### 7.2 Post Creation Flow
```
┌──────────┐   1. POST /api/v1/posts   ┌──────────────┐
│  Client  │ ─────────────────────────► │   Backend    │
│ (Next.js)│                           │    (.NET)     │
└──────────┘                           └──────┬───────┘
      ▲                                       │
      │                                       │
      │  2. CreatePostCommandHandler          │
      │     - Validate request                │
      │     - Business rules                  │
      │     - Save to DB                      │
      │                                       │
      │                                       ▼
      │                              ┌──────────────┐
      │                              │ PostgreSQL   │
      │                              │   Database   │
      │                              └──────┬───────┘
      │                                     │
      │                                     │
      │  3. Publish event to RabbitMQ       │
      │     - ArticleCreatedEvent           │
      │                                     │
      │                                     │
      │                              ┌──────▼───────┐
      │                              │  RabbitMQ    │
      │                              │ (blog.events)│
      │                              └──────┬───────┘
      │                                     │
      │                                     │
      │  4. Consume by AI Service           │
      │                                     │
      │                                     ▼
      │                              ┌──────────────┐
      │                              │ AI Service   │
      │                              │  (Python)    │
      │                              └──────┬───────┘
      │                                     │
      │  5. Generate AI analysis            │
      │     - Summary                       │
      │     - Keywords                     │
      │     - Sentiment                    │
      │     - Reading time                 │
      │                                     │
      │  6. Index for RAG                  │
      │     - ChromaDB                     │
      │                                     │
      │  7. Publish result                 │
      │     - AiAnalysisCompletedEvent     │
      │                                     │
      │                                     │
      └─────────────────────────────────────────────────────┘
      │
      │  8. Update post with AI data
      │
      │  9. Broadcast via SignalR
      │     - CacheInvalidated
      │
      ▼
┌──────────┐
│  Client  │  Invalidate cache, refresh UI
└──────────┘
```

### 7.3 Article Chat Flow (RAG)
```
┌──────────┐   1. POST /api/v1/chat   ┌──────────────┐
│  Client  │ ────────────────────────► │   Backend    │
│ (Next.js)│                           │    (.NET)     │
└──────────┘                           └──────┬───────┘
      ▲                                       │
      │                                       │
      │  2. Publish ChatRequestedEvent        │
      │                                       │
      │                              ┌───────▼────────┐
      │                              │   RabbitMQ     │
      │                              │ (blog.events)  │
      │                              └───────┬────────┘
      │                                      │
      │                                      │
      │  3. Consume by AI Service            │
      │                                      │
      │                                      ▼
      │                              ┌──────────────┐
      │                              │ AI Service   │
      │                              │  (Python)    │
      │                              └──────┬───────┘
      │                                     │
      │  4. RAG Process                     │
      │     a. Search ChromaDB for          │
      │        relevant article chunks     │
      │     b. Build context                │
      │     c. Stream LLM response          │
      │                                      │
      │                                      │
      │  5. Publish ChatResponseEvent       │
      │     (streaming via SignalR)         │
      │                                      │
      │                                      │
      └──────────────────────────────────────────────────────┘
      │
      │  6. SignalR: ChatMessageReceived
      │     - Stream chunks to UI
      │
      ▼
┌──────────┐
│  Client  │  Display streaming response
└──────────┘
```

---

## 8. Güvenlik Mimarisi

### 8.1 Authentication
- **JWT Access Token**: 60 dakika geçerlilik süresi
- **Refresh Token**: 30 gün geçerlilik, veritabanında saklanır
- **HttpOnly Cookies**: XSS koruması için
- **SameSite=Strict**: CSRF koruması için
- **Secure Flag**: HTTPS sadece

### 8.2 Authorization
- **Role-Based Access Control (RBAC)**:
  - **Admin**: Tam erişim
  - **Editor**: Yayınla/yayından kaldır
  - **Author**: Kendi postlarını oluştur/düzenle
  - **Reader**: Salt okunur

### 8.3 Rate Limiting
- **IP-based**: Her IP adresi için limit
- **Endpoint-based**: Her endpoint için farklı limitler
- **AI Service**: Daha sıkı limitler (pahalı işlemler)

| Endpoint | Limit |
|----------|-------|
| `/api/v1/auth/login` | 10/dakika |
| `/api/v1/posts` (GET) | 100/dakika |
| `/api/v1/posts` (POST) | 20/dakika |
| `/api/v1/ai/*` | 10/dakika |
| `/api/chat/stream` | 60/dakika |

### 8.4 Account Lockout
- 5 başarısız giriş → 30 dakika lockout
- IP address tracking
- Failed login attempts logging

### 8.5 CSRF Protection
- Antiforgery cookies
- Header name: `X-CSRF-TOKEN`
- SameSite=Strict cookies

### 8.6 Security Headers
```csharp
// Custom middleware
app.UseSecurityHeaders();

// Headers:
// X-Content-Type-Options: nosniff
// X-Frame-Options: DENY
// X-XSS-Protection: 1; mode=block
// Strict-Transport-Security: max-age=31536000; includeSubDomains
// Content-Security-Policy: default-src 'self'
```

### 8.7 Input Validation
- **FluentValidation**: Backend validation
- **Zod**: Frontend validation
- **SQL Injection**: EF Core parameterized queries
- **XSS**: React auto-escaping

### 8.8 Secrets Management
- Environment variables
- No hardcoded secrets
- Gitignored `.env` files
- User Secrets for development

---

## 9. Performans Optimizasyonları

### 9.1 Caching Stratejisi

#### Frontend Caching
- **ISR (Incremental Static Regeneration)**:
  - Posts: 60 saniye
  - Categories/Tags: 300 saniye
- **Zustand In-Memory Cache**: 5 dakika
- **Cache Version Tracking**: Reactive invalidation

#### Backend Caching
- **L1 (Memory)**: Ultra hızlı, instance başına
- **L2 (Redis)**: Paylaşılan cache
- **SWR**: Eski veriyi göster, arka planda güncelle
- **Cache Group Invalidation**: Prefix bazlı temizleme

### 9.2 Database Optimizasyonları
- **PostgreSQL Full-Text Search**: `tsvector` kolonu
- **Partial Indexes**: Sadece yayınlanmış postlar için
- **Query Optimization**: Entity-specific repositories
- **Connection Pooling**: EF Core connection pool

### 9.3 API Optimizasyonları
- **Output Caching**: HTTP response cache
- **Compression**: Brotli/Gzip
- **Pagination**: Tüm listeler paginate
- **Projection**: Sadece gerekli alanlar select

### 9.4 Frontend Optimizasyonları
- **Code Splitting**: Next.js automatic
- **Image Optimization**: next/image
- **Lazy Loading**: Dinamik import
- **Server Components**: İstemci tarafı JS azaltma

### 9.5 Monitoring
- **OpenTelemetry Metrics**: `/metrics` endpoint (Prometheus)
- **Serilog Logging**: Structured logs
- **Cache Metrics**: Hit/miss ratios
- **Performance Counters**: Response times

---

## 10. Deployment Stratejisi

### 10.1 Docker Compose (Development)

```yaml
# docker-compose.yml
version: '3.8'

services:
  blogapp-api:
    build:
      context: ./src/BlogApp.Server/BlogApp.Server.Api
      dockerfile: Dockerfile
    ports:
      - "5116:8080"
    environment:
      - ASPNETCORE_ENVIRONMENT=Development
      - ConnectionStrings__DefaultConnection=Host postgres;Database=blogapp;Username=blogapp;Password=blogapp_password
      - ConnectionStrings__Redis=redis:6379
      - JwtSettings__Secret=${JWT_SECRET}
    depends_on:
      - postgres
      - redis
      - rabbitmq

  blogapp-web:
    build:
      context: ./src/blogapp-web
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:5116/api/v1
    depends_on:
      - blogapp-api

  ai-agent-service:
    build:
      context: ./src/services/ai-agent-service
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - REDIS_URL=redis://redis:6379/0
      - RABBITMQ_HOST=rabbitmq
    depends_on:
      - ollama
      - redis
      - rabbitmq

  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=blogapp
      - POSTGRES_USER=blogapp
      - POSTGRES_PASSWORD=blogapp_password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  rabbitmq:
    image: rabbitmq:3.12-management
    environment:
      - RABBITMQ_DEFAULT_USER=admin
      - RABBITMQ_DEFAULT_PASS=${RABBITMQ_PASSWORD}
    ports:
      - "5672:5672"
      - "15672:15672"  # Management UI
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"

volumes:
  postgres_data:
  redis_data:
  rabbitmq_data:
  ollama_data:
```

### 10.2 Production Deployment

#### Kubernetes (Önerilen)
- **API**: Horizontal Pod Autoscaler (HPA)
- **Web**: Static CDN (Cloudflare/Vercel)
- **AI Service**: HPA based on queue length
- **PostgreSQL**: Managed database (Cloud SQL/RDS)
- **Redis**: Redis Cluster
- **RabbitMQ**: RabbitMQ Cluster

#### Docker Swarm (Basit Alternatif)
- Stack deployment
- Service scaling
- Rolling updates

---

## 11. Sonuç

### 11.1 Güçlü Yanlar
1. **Modern Stack**: Next.js 16 + .NET 10 + Python 3.12
2. **Clean Architecture**: Katmanların net ayrımı
3. **Event-Driven**: RabbitMQ ile asenkron AI işleme
4. **Real-Time**: SignalR ile anlık güncellemeler
5. **SEO-Friendly**: ISR, schema.org, dynamic metadata
6. **Scalable**: Building blocks pattern, microservices-ready
7. **Secure**: JWT, refresh tokens, rate limiting, RBAC
8. **AI-Powered**: RAG, content generation, chat assistant
9. **Observable**: OpenTelemetry metrics, Serilog logging
10. **Production-Ready**: Docker, health checks, graceful degradation

### 11.2 Teknik Highlights
- **CQRS + MediatR**: Command/Query separation
- **Entity-Specific Repositories**: Type-safe operations
- **Unit of Work**: Transaction management
- **Hybrid Cache (L1+L2)**: Optimal performance
- **Stale-While-Revalidate**: Fresh data with UX
- **Hexagonal Architecture (AI Service)**: Clean domain logic
- **RAG + Vector Search**: Contextual AI responses
- **Local LLM (Ollama)**: No API costs, privacy
- **Multi-Level Caching**: ISR → Memory → Redis → Database
- **SignalR Streaming**: Real-time AI responses

---

**Rapor Hazırlayan:** Claude Code Agent
**Son Güncelleme:** 2026-01-31
