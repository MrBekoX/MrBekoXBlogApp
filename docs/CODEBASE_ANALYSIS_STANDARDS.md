# Codebase Analysis Standards and Best Practices Reference Guide

This comprehensive reference guide provides checklists and criteria for analyzing codebases against established software engineering standards and best practices. It is designed to be used by agents performing code quality analysis, security audits, and architecture reviews.

**Last Updated:** 2025-02-05
**Version:** 1.0

---

## Table of Contents

1. [SOLID Principles](#1-solid-principles)
2. [Security Best Practices](#2-security-best-practices)
3. [Clean Code Standards](#3-clean-code-standards)
4. [Architecture Patterns](#4-architecture-patterns)
5. [OWASP Top 10](#5-owasp-top-10-2025)

---

## 1. SOLID Principles

### 1.1 Single Responsibility Principle (SRP)

**Definition:** A class should have one and only one reason to change, meaning it should have only one job.

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| SRP-001 | Does each class/module have only one responsibility? | [ ] |
| SRP-002 | Can the class be described with a single verb phrase? | [ ] |
| SRP-003 | Are there multiple reasons to modify the class? | [ ] |
| SRP-004 | Does the class combine multiple concerns (e.g., data access + validation + UI)? | [ ] |
| SRP-005 | Are methods grouped logically by responsibility? | [ ] |

**Common Violations:**
- Controllers containing business logic and data access
- Classes with multiple unrelated methods
- God objects that handle too many responsibilities
- Mixing concerns like validation, persistence, and notification

**Remediation Patterns:**
- Extract classes based on responsibilities
- Use Facade pattern for coordinating multiple responsibilities
- Apply Separation of Concerns principle

### 1.2 Open/Closed Principle (OCP)

**Definition:** Software entities should be open for extension but closed for modification.

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| OCP-001 | Can behavior be extended without modifying existing code? | [ ] |
| OCP-002 | Are abstractions (interfaces/abstract classes) used for extensibility? | [ ] |
| OCP-003 | Does changing one feature require modifying unrelated code? | [ ] |
| OCP-004 | Are strategies/patterns used to enable runtime extension? | [ ] |
| OCP-005 | Is configuration used instead of code changes? | [ ] |

**Common Violations:**
- Large switch/case or if-else chains
- Hardcoded business rules that require code changes
- Direct instantiation of concrete dependencies
- Lack of abstraction for varying implementations

**Remediation Patterns:**
- Strategy Pattern
- Template Method Pattern
- Dependency Injection
- Plugin Architecture

### 1.3 Liskov Substitution Principle (LSP)

**Definition:** Objects of a superclass should be replaceable with objects of its subclasses without breaking the application.

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| LSP-001 | Can subclass objects replace parent class objects seamlessly? | [ ] |
| LSP-002 | Does the subclass strengthen preconditions? | [ ] |
| LSP-003 | Does the subclass weaken postconditions? | [ ] |
| LSP-004 | Are return types covariant (compatible)? | [ ] |
| LSP-005 | Are exception types contravariant (subclass or same)? | [ ] |
| LSP-006 | Does the subclass violate base class invariants? | [ ] |

**Common Violations:**
- Subclasses throwing exceptions not thrown by base class
- Subclasses returning null when base class doesn't
- Subclasses ignoring base class behavior completely
- Square/Rectangle inheritance problem

**Remediation Patterns:**
- Composition over inheritance
- Use interfaces instead of base classes
- Apply Design by Contract

### 1.4 Interface Segregation Principle (ISP)

**Definition:** Clients should not be forced to depend on interfaces they don't use.

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| ISP-001 | Are interfaces focused and minimal? | [ ] |
| ISP-002 | Do clients depend on methods they don't use? | [ ] |
| ISP-003 | Are there "fat" interfaces with many unrelated methods? | [ ] |
| ISP-004 | Do implementations contain stub/empty methods? | [ ] |
| ISP-005 | Can interfaces be split into role-specific ones? | [ ] |

**Common Violations:**
- Large monolithic interfaces
- Classes implementing methods they don't use (with empty bodies)
- God interfaces that combine multiple responsibilities
- Interface methods unused by some clients

**Remediation Patterns:**
- Split interfaces into smaller, focused ones
- Use interface composition
- Apply Role-Based Interfaces

### 1.5 Dependency Inversion Principle (DIP)

**Definition:** High-level modules should not depend on low-level modules; both should depend on abstractions. Abstractions should not depend on details; details should depend on abstractions.

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| DIP-001 | Do high-level modules depend on abstractions, not concretions? | [ ] |
| DIP-002 | Are dependencies injected (not created internally)? | [ ] |
| DIP-003 | Do low-level modules depend on abstractions? | [ ] |
| DIP-004 | Can implementations be swapped without changing high-level code? | [ ] |
| DIP-005 | Are there direct dependencies on concrete classes? | [ ] |

**Common Violations:**
- Direct instantiation of dependencies with `new`
- High-level modules depending on low-level details
- Static method calls to concrete implementations
- Tight coupling to external libraries/frameworks

**Remediation Patterns:**
- Dependency Injection (Constructor, Property, Method)
- Inversion of Control (IoC) Containers
- Abstract Factory Pattern
- Service Locator Pattern (use sparingly)

---

## 2. Security Best Practices

### 2.1 .NET/C# Security Best Practices

**Analysis Checklist:**

| Category | Criterion | Description | Status |
|----------|-----------|-------------|--------|
| Authentication | AUTH-001 | Is ASP.NET Core Identity used for authentication? | [ ] |
| Authentication | AUTH-002 | Are passwords hashed using PBKDF2, Argon2, or BCrypt? | [ ] |
| Authentication | AUTH-003 | Is JWT token validation implemented correctly? | [ ] |
| Authentication | AUTH-004 | Is refresh token rotation implemented? | [ ] |
| Authorization | AUTHZ-001 | Is authorization checked on every request? | [ ] |
| Authorization | AUTHZ-002 | Are role-based claims used for authorization? | [ ] |
| Authorization | AUTHZ-003 | Is resource-based authorization implemented? | [ ] |
| Data Protection | DP-001 | Are sensitive secrets stored in Azure Key Vault? | [ ] |
| Data Protection | DP-002 | Are connection strings encrypted? | [ ] |
| Data Protection | DP-003 | Is Data Protection API used for sensitive data? | [ ] |
| Input Validation | IV-001 | Is all user input validated? | [ ] |
| Input Validation | IV-002 | Are parameterized queries used? | [ ] |
| Input Validation | IV-003 | Is output encoding applied (XSS prevention)? | [ ] |
| Security Headers | SH-001 | Is HTTPS enforced with HSTS? | [ ] |
| Security Headers | SH-002 | Is Content Security Policy configured? | [ ] |
| Security Headers | SH-003 | Are X-Frame-Options, X-Content-Type-Options set? | [ ] |
| Security Headers | SH-004 | Is Referrer-Policy configured? | [ ] |
| Cookies | COOK-001 | Are cookies set with HttpOnly flag? | [ ] |
| Cookies | COOK-002 | Are cookies set with Secure flag? | [ ] |
| Cookies | COOK-003 | Is SameSite set to Strict or Lax? | [ ] |
| Error Handling | ERR-001 | Are stack traces not exposed to clients? | [ ] |
| Error Handling | ERR-002 | Are generic error messages used for security failures? | [ ] |
| Dependencies | DEP-001 | Are NuGet packages regularly updated? | [ ] |
| Dependencies | DEP-002 | Is Dependabot or similar tool configured? | [ ] |

**Key Security Middleware:**
```csharp
// Required security middleware
app.UseHsts();
app.UseHttpsRedirection();
app.UseAuthentication();
app.UseAuthorization();
app.UseMiddleware<ExceptionHandlingMiddleware>();
```

### 2.2 Node.js/Next.js Security Best Practices

**Analysis Checklist:**

| Category | Criterion | Description | Status |
|----------|-----------|-------------|--------|
| Configuration | CFG-001 | Is `NEXT_PUBLIC` used only for non-sensitive data? | [ ] |
| Configuration | CFG-002 | Are API keys in server-side environment variables only? | [ ] |
| Configuration | CFG-003 | Is `.env.local` in `.gitignore`? | [ ] |
| Authentication | AUTH-N-001 | Is NextAuth.js or similar used? | [ ] |
| Authentication | AUTH-N-002 | Are session tokens stored securely (httpOnly cookies)? | [ ] |
| Input Validation | IV-N-001 | Is Zod or similar used for validation? | [ ] |
| Input Validation | IV-N-002 | Is user input sanitized before rendering? | [ ] |
| XSS Prevention | XSS-001 | Is `dangerouslySetInnerHTML` avoided or sanitized? | [ ] |
| XSS Prevention | XSS-002 | Is JSX auto-escaping leveraged? | [ ] |
| CSRF Protection | CSRF-001 | Is CSRF token validation implemented? | [ ] |
| Security Headers | SH-N-001 | Is `next.config.js` security headers configured? | [ ] |
| Security Headers | SH-N-002 | Is Content Security Policy set? | [ ] |
| API Routes | API-001 | Are API routes protected with authentication? | [ ] |
| API Routes | API-002 | Is rate limiting implemented? | [ ] |
| Dependencies | DEP-N-001 | Is `npm audit` run regularly? | [ ] |
| Dependencies | DEP-N-002 | Are dependencies pinned to specific versions? | [ ] |

**Next.js Security Configuration:**
```javascript
// next.config.js - Recommended security headers
module.exports = {
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=()',
          },
        ],
      },
    ];
  },
};
```

### 2.3 Python/FastAPI Security Best Practices

**Analysis Checklist:**

| Category | Criterion | Description | Status |
|----------|-----------|-------------|--------|
| Configuration | CFG-P-001 | Is python-dotenv used for environment variables? | [ ] |
| Configuration | CFG-P-002 | Are secrets not hardcoded? | [ ] |
| Authentication | AUTH-P-001 | Is JWT or OAuth2 implemented correctly? | [ ] |
| Authentication | AUTH-P-002 | Are passwords hashed with bcrypt/argon2? | [ ] |
| Input Validation | IV-P-001 | Is Pydantic used for request validation? | [ ] |
| Input Validation | IV-P-002 | Is SQL injection prevented with parameterized queries? | [ ] |
| CORS | CORS-001 | Is CORS properly configured (not wildcard)? | [ ] |
| CORS | CORS-002 | Are origins whitelisted explicitly? | [ ] |
| Dependencies | DEP-P-001 | Is `pip-audit` or `safety` used? | [ ] |
| Dependencies | DEP-P-002 | Are requirements.txt/requirements.lock maintained? | [ ] |
| Rate Limiting | RL-001 | Is slowapi or similar rate limiter used? | [ ] |
| Security Headers | SH-P-001 | Is security middleware used? | [ ] |
| Error Handling | ERR-P-001 | Are detailed errors not exposed in production? | [ ] |
| Logging | LOG-P-001 | Are sensitive data not logged? | [ ] |
| Logging | LOG-P-002 | Is structured logging implemented? | [ ] |

**FastAPI Security Best Practices:**
```python
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPBearer

security = HTTPBearer()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://example.com"],  # Not "*"
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization"],
)

# Trusted host
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["example.com", "*.example.com"]
)
```

### 2.4 Docker Container Security Best Practices

**Analysis Checklist:**

| Category | Criterion | Description | Status |
|----------|-----------|-------------|--------|
| Base Images | IMG-001 | Are minimal/alpine base images used? | [ ] |
| Base Images | IMG-002 | Are base images pinned to specific versions? | [ ] |
| Base Images | IMG-003 | Are images from trusted registries? | [ ] |
| Container Configuration | CNF-001 | Is container running as non-root user? | [ ] |
| Container Configuration | CNF-002 | Is filesystem read-only where possible? | [ ] |
| Container Configuration | CNF-003 | Are capabilities dropped (--cap-drop)? | [ ] |
| Container Configuration | CNF-004 | Is --no-new-privileges flag set? | [ ] |
| Container Configuration | CNF-005 | Is seccomp profile configured? | [ ] |
| Container Configuration | CNF-006 | Is AppArmor/SELinux profile applied? | [ ] |
| Secrets Management | SEC-001 | Are secrets not in environment variables? | [ ] |
| Secrets Management | SEC-002 | Are secrets mounted as files (not env vars)? | [ ] |
| Secrets Management | SEC-003 | Is Docker secrets or similar used? | [ ] |
| Network Security | NET-001 | Are container networks isolated? | [ ] |
| Network Security | NET-002 | Is host networking avoided? | [ ] |
| Image Scanning | SCAN-001 | Are images scanned for vulnerabilities? | [ ] |
| Image Scanning | SCAN-002 | Is scanning integrated in CI/CD? | [ ] |
| Dockerfile Security | DF-001 | Is multi-stage build used? | [ ] |
| Dockerfile Security | DF-002 | Are credentials not in Dockerfile? | [ ] |
| Dockerfile Security | DF-003 | Is HEALTHCHECK implemented? | [ ] |
| Runtime Security | RUN-001 | Is container runtime monitored? | [ ] |
| Runtime Security | RUN-002 | Are resource limits configured? | [ ] |

**Secure Dockerfile Template:**
```dockerfile
# Use specific version, minimal image
FROM python:3.12-slim AS builder

# Non-root user
RUN adduser --disabled-password --gecos '' appuser

# Multi-stage build
FROM python:3.12-slim

# Copy only necessary files
COPY --from=builder /app /app

# Non-root
USER appuser

# Read-only filesystem
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    python3 && rm -rf /var/lib/apt/lists/*

# Drop capabilities, no new privileges
# Health check
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:8000/health || exit 1

USER appuser
```

**Seccomp Profile Example:**
```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "syscalls": [
    {
      "name": "read",
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "name": "write",
      "action": "SCMP_ACT_ALLOW"
    }
    // Whitelist only necessary syscalls
  ]
}
```

---

## 3. Clean Code Standards

### 3.1 DRY (Don't Repeat Yourself)

**Definition:** Every piece of knowledge must have a single, unambiguous, authoritative representation within a system.

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| DRY-001 | Is there code duplication across files? | [ ] |
| DRY-002 | Are similar algorithms consolidated? | [ ] |
| DRY-003 | Is magic strings/numbers replaced with constants? | [ ] |
| DRY-004 | Are utility functions extracted for reuse? | [ ] |
| DRY-005 | Are base classes/traits used for shared behavior? | [ ] |
| DRY-006 | Is configuration centralized? | [ ] |
| DRY-007 | Are validation rules reusable? | [ ] |

**Common Violations:**
- Copy-pasted code blocks
- Similar if-else chains in multiple places
- Repeated validation logic
- Duplicated database queries

**Remediation Patterns:**
- Extract Method
- Extract Class
- Template Method Pattern
- Create shared utility libraries

### 3.2 KISS (Keep It Simple, Stupid)

**Definition:** Most systems work best if they are kept simple rather than made complicated; simplicity should be a key goal in design, and unnecessary complexity should be avoided.

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| KISS-001 | Is the code easy to understand? | [ ] |
| KISS-002 | Are there unnecessary abstractions? | [ ] |
| KISS-003 | Is cyclomatic complexity low (<10 per method)? | [ ] |
| KISS-004 | Are nested levels minimal (<4)? | [ ] |
| KISS-005 | Is the simplest solution chosen? | [ ] |
| KISS-006 | Are functions short (<50 lines)? | [ ] |
| KISS-007 | Is premature optimization avoided? | [ ] |

**Common Violations:**
- Over-engineering
- Unnecessary design patterns
- Complex nested logic
- Clever but unreadable code

**Remediation Patterns:**
- Simplify conditional logic
- Use guard clauses
- Break down large functions
- Remove unnecessary abstractions

### 3.3 YAGNI (You Aren't Gonna Need It)

**Definition:** Always implement things when you actually need them, never when you just foresee that you may need them.

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| YAGNI-001 | Is there unused code? | [ ] |
| YAGNI-002 | Are there "just in case" features? | [ ] |
| YAGNI-003 | Is there commented-out code? | [ ] |
| YAGNI-004 | Are there unused parameters/variables? | [ ] |
| YAGNI-005 | Are there speculative abstractions? | [ ] |
| YAGNI-006 | Is dead code regularly removed? | [ ] |

**Common Violations:**
- Unused functions/methods
- Features "for the future"
- Commented code blocks
- Speculative generalizations

**Remediation Patterns:**
- Delete unused code immediately
- Focus on current requirements
- Defer abstractions until needed

---

## 4. Architecture Patterns

### 4.1 Clean Architecture

**Definition:** An architecture that separates concerns into layers with dependency rules: dependencies only point inward.

**Layer Structure:**
```
┌─────────────────────────────────────────┐
│         Frameworks & Drivers            │  (UI, DB, Web, Frameworks)
├─────────────────────────────────────────┤
│            Interface Adapters            │  (Controllers, Presenters, Gateways)
├─────────────────────────────────────────┤
│            Use Cases (Application)      │  (Business Rules)
├─────────────────────────────────────────┤
│               Entities                  │  (Enterprise Business Rules)
└─────────────────────────────────────────┘
```

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| CA-001 | Are dependencies inward only? | [ ] |
| CA-002 | Is business logic independent of frameworks? | [ ] |
| CA-003 | Can UI/DB be replaced without changing business rules? | [ ] |
| CA-004 | Are entities framework-agnostic? | [ ] |
| CA-005 | Is there clear separation of concerns? | [ ] |
| CA-006 | Do use cases not depend on external systems? | [ ] |

**Directory Structure Reference:**
```
src/
  Domain/              # Entities (no dependencies)
  Application/         # Use cases (depends on Domain)
  Infrastructure/      # External concerns (depends on Application)
  Presentation/        # UI (depends on Application)
```

### 4.2 Hexagonal Architecture (Ports and Adapters)

**Definition:** An architecture that separates the core application from external concerns using ports (interfaces) and adapters (implementations).

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| HEX-001 | Are ports defined as interfaces? | [ ] |
| HEX-002 | Are adapters external to the core? | [ ] |
| HEX-003 | Is core independent of infrastructure? | [ ] |
| HEX-004 | Can adapters be swapped without changing core? | [ ] |
| HEX-005 | Are there driving (primary) adapters? | [ ] |
| HEX-006 | Are there driven (secondary) adapters? | [ ] |

**Port/Adapter Examples:**
- **Ports (Interfaces):** `IUserRepository`, `IEmailService`, `IPaymentGateway`
- **Adapters (Implementations):** `SqlUserRepository`, `SmtpEmailService`, `StripePaymentGateway`

### 4.3 CQRS (Command Query Responsibility Segregation)

**Definition:** A pattern that separates read (query) operations from write (command) operations.

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| CQRS-001 | Are commands and queries separated? | [ ] |
| CQRS-002 | Do commands not return data (only status)? | [ ] |
| CQRS-003 | Do queries not modify state? | [ ] |
| CQRS-004 | Is there separate read/write models? | [ ] |
| CQRS-005 | Is eventual consistency handled? | [ ] |

**CQRS Structure:**
```
Commands (Write)              Queries (Read)
  CreatePostCommand             GetPostQuery
  UpdatePostCommand            GetPostsListQuery
  DeletePostCommand            SearchPostsQuery
    |                              |
    v                              v
CommandHandler                QueryHandler
    |                              |
    v                              v
Write Model                   Read Model (DTO/Projection)
```

### 4.4 Repository Pattern

**Definition:** A pattern that mediates between the domain and data mapping layers, acting like an in-memory domain object collection.

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| REP-001 | Is repository interface in domain layer? | [ ] |
| REP-002 | Is repository implementation in infrastructure? | [ ] |
| REP-003 | Are repositories focused on aggregates? | [ ] |
| REP-004 | Is there generic repository for common operations? | [ ] |
| REP-005 | Do repositories not expose ORM details? | [ ] |
| REP-006 | Is Unit of Work pattern used? | [ ] |

**Repository Interface Example:**
```csharp
// Domain layer - interface
public interface IBlogPostRepository
{
    Task<BlogPost?> GetByIdAsync(Guid id);
    Task<IEnumerable<BlogPost>> GetAllAsync();
    Task AddAsync(BlogPost post);
    Task UpdateAsync(BlogPost post);
    Task DeleteAsync(BlogPost post);
}

// Infrastructure layer - implementation
public class EfCoreBlogPostRepository : IBlogPostRepository
{
    private readonly AppDbContext _context;
    // Implementation using EF Core
}
```

---

## 5. OWASP Top 10 (2025)

### Overview of OWASP Top 10:2025

| Code | Risk Category | Description |
|------|---------------|-------------|
| A01 | Broken Access Control | Users can act outside of their intended permissions |
| A02 | Security Misconfiguration | Improper configuration of security controls |
| A03 | Software Supply Chain Failures | Vulnerabilities in dependencies and supply chain |
| A04 | Cryptographic Failures | Failure to properly protect sensitive data |
| A05 | Injection | Untrusted data interpreted as code |
| A06 | Insecure Design | Architecture and design flaws |
| A07 | Authentication Failures | Weaknesses in identity and authentication |
| A08 | Software or Data Integrity Failures | Code or infrastructure integrity issues |
| A09 | Security Logging and Alerting Failures | Insufficient logging and monitoring |
| A10 | Mishandling of Exceptional Conditions | Improper error and exception handling |

### 5.1 A01: Broken Access Control

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| A01-001 | Is authorization checked on every request? | [ ] |
| A01-002 | Are users prevented from accessing others' resources? | [ ] |
| A01-003 | Is IDOR (Insecure Direct Object Reference) prevented? | [ ] |
| A01-004 | Are API endpoints protected with proper roles? | [ ] |
| A01-005 | Is server-side validation enforced (not just client-side)? | [ ] |
| A01-006 | Are mass assignment attacks prevented? | [ ] |
| A01-007 | Is access logging implemented? | [ ] |

### 5.2 A02: Security Misconfiguration

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| A02-001 | Are default credentials changed? | [ ] |
| A02-002 | Is debug mode disabled in production? | [ ] |
| A02-003 | Are error messages not exposing sensitive info? | [ ] |
| A02-004 | Are security headers properly configured? | [ ] |
| A02-005 | Is CORS configured correctly? | [ ] |
| A02-006 | Are unused features disabled? | [ ] |
| A02-007 | Is configuration hardened for production? | [ ] |

### 5.3 A03: Software Supply Chain Failures

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| A03-001 | Are dependencies regularly updated? | [ ] |
| A03-002 | Is SBOM (Software Bill of Materials) maintained? | [ ] |
| A03-003 | Are dependencies scanned for vulnerabilities? | [ ] |
| A03-004 | Are code signing and provenance checks in place? | [ ] |
| A03-005 | Is vendor software verified before use? | [ ] |
| A03-006 | Are unpinned dependencies avoided? | [ ] |

### 5.4 A04: Cryptographic Failures

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| A04-001 | Is data encrypted at rest? | [ ] |
| A04-002 | Is data encrypted in transit (TLS)? | [ ] |
| A04-003 | Are strong algorithms used (AES-256, RSA-2048+)? | [ ] |
| A04-004 | Are keys properly managed and rotated? | [ ] |
| A04-005 | Is sensitive data not logged? | [ ] |
| A04-006 | Are deprecated algorithms avoided (MD5, SHA1)? | [ ] |

### 5.5 A05: Injection

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| A05-001 | Are parameterized queries used? | [ ] |
| A05-002 | Is input validation and sanitization implemented? | [ ] |
| A05-003 | Is ORM used correctly? | [ ] |
| A05-004 | Are stored procedures with parameters used? | [ ] |
| A05-005 | Is output encoding applied? | [ ] |
| A05-006 | Are NoSQL injection attacks prevented? | [ ] |
| A05-007 | Is command injection prevented? | [ ] |

### 5.6 A06: Insecure Design

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| A06-001 | Is threat modeling performed? | [ ] |
| A06-002 | Are security requirements defined? | [ ] |
| A06-003 | Is rate limiting implemented? | [ ] |
| A06-004 | Are business logic vulnerabilities addressed? | [ ] |
| A06-005 | Is anti-automation implemented? | [ ] |

### 5.7 A07: Authentication Failures

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| A07-001 | Are passwords hashed with strong algorithms? | [ ] |
| A07-002 | Is password complexity enforced? | [ ] |
| A07-003 | Is account lockout implemented? | [ ] |
| A07-004 | Is multi-factor authentication available? | [ ] |
| A07-005 | Are session timeouts configured? | [ ] |
| A07-006 | Is secure session management implemented? | [ ] |

### 5.8 A08: Software or Data Integrity Failures

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| A08-001 | Is code signing implemented? | [ ] |
| A08-002 | Are integrity checks performed on updates? | [ ] |
| A08-003 | Is CI/CD pipeline secured? | [ ] |
| A08-004 | Are deserialization attacks prevented? | [ ] |

### 5.9 A09: Security Logging and Alerting Failures

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| A09-001 | Are security events logged? | [ ] |
| A09-002 | Are logs tamper-evident? | [ ] |
| A09-003 | Is log correlation implemented? | [ ] |
| A09-004 | Are alerts configured for critical events? | [ ] |
| A09-005 | Are logs not containing sensitive data? | [ ] |
| A09-006 | Is log retention policy defined? | [ ] |

### 5.10 A10: Mishandling of Exceptional Conditions

**Analysis Checklist:**

| Criterion | Description | Status |
|-----------|-------------|--------|
| A10-001 | Are exceptions caught and handled gracefully? | [ ] |
| A10-002 | Are stack traces not exposed to users? | [ ] |
| A10-003 | Is generic error messaging used? | [ ] |
| A10-004 | Is error logging implemented? | [ ] |
| A10-005 | Are DoS conditions handled? | [ ] |

---

## Scoring System

For each category, calculate a compliance score:

```
Score = (Passed Checks / Total Checks) * 100
```

**Rating Scale:**
- **90-100%**: Excellent - Follows best practices
- **70-89%**: Good - Minor improvements needed
- **50-69%**: Fair - Significant improvements needed
- **<50%**: Poor - Requires immediate attention

---

## Analysis Report Template

When performing a codebase analysis, use the following structure:

```markdown
# Codebase Analysis Report

## Executive Summary
- Overall Compliance Score: X%
- Critical Issues: X
- High Priority Issues: X
- Medium Priority Issues: X
- Low Priority Issues: X

## 1. SOLID Principles Analysis
- SRP: X% - [Description]
- OCP: X% - [Description]
- LSP: X% - [Description]
- ISP: X% - [Description]
- DIP: X% - [Description]

## 2. Security Analysis
### 2.1 .NET Security
- Score: X%
- Findings: [List]

### 2.2 Next.js Security
- Score: X%
- Findings: [List]

### 2.3 Python/FastAPI Security
- Score: X%
- Findings: [List]

### 2.4 Docker Security
- Score: X%
- Findings: [List]

## 3. Clean Code Analysis
- DRY: X%
- KISS: X%
- YAGNI: X%

## 4. Architecture Analysis
- Clean Architecture: [Compliant/Non-Compliant]
- Hexagonal Architecture: [Compliant/Non-Compliant]
- CQRS: [Compliant/Non-Compliant]
- Repository Pattern: [Compliant/Non-Compliant]

## 5. OWASP Top 10 Compliance
| Risk | Status | Notes |
|------|--------|-------|
| A01 | [Pass/Fail] | |
| A02 | [Pass/Fail] | |
| ... | | |

## Recommendations
1. [Critical recommendations]
2. [High priority recommendations]
3. [Medium priority recommendations]
```

---

## References

1. [SOLID Principles - DigitalOcean](https://www.digitalocean.com/community/conceptual-articles/s-o-l-i-d-the-first-five-principles-of-object-oriented-design)
2. [SOLID Principles - Baeldung](https://www.baeldung.com/solid-principles)
3. [SOLID Principles with Real Life Examples - GeeksforGeeks](https://www.geeksforgeeks.org/system-design/solid-principle-in-programming-understand-with-real-life-examples/)
4. [OWASP Top 10:2025](https://owasp.org/Top10/2025/)
5. [OWASP .NET Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/DotNet_Security_Cheat_Sheet.html)
6. [OWASP Node.js Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Nodejs_Security_Cheat_Sheet.html)
7. [OWASP Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
8. [Complete Next.js Security Guide 2025](https://www.turbostarter.dev/blog/complete-nextjs-security-guide-2025-authentication-api-protection-and-best-practices)
9. [FastAPI Security Best Practices](https://medium.com/@yogeshkrishnanseeniraj/fastapi-security-best-practices-defending-against-common-threats-58fbd6a15fd2)
10. [Clean Code Principles 2025](https://www.pullchecklist.com/posts/clean-code-principles)
11. [DDD, Hexagonal, Onion, Clean, CQRS - Herberto Graça](https://herbertograca.com/2017/11/16/explicit-architecture-01-ddd-hexagonal-onion-clean-cqrs-how-i-put-it-all-together/)
12. [Docker Security Best Practices - AquaSec](https://www.aquasec.com/blog/docker-security-best-practices/)
13. [Docker Hardening - Docker Docs](https://docs.docker.com/dhi/core-concepts/hardening/)
