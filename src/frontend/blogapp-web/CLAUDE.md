# Frontend (blogapp-web)

> Bu dosya `src/frontend/blogapp-web/` altinda calisirken otomatik yuklenir.
> Genel frontend kurallari: `.claude/rules/frontend.md` (bazi yerleri tarihsel — gercek yapi asagidaki).
> Genel proje kurallari: `.claude/CLAUDE.md`.

## Stack (gercek versiyonlar — `package.json`)

- **Next.js 16.1.6** (App Router) + **React 19.2.3** + **TypeScript 5**
- **State:** Zustand 5.0.9
- **Form:** React Hook Form 7.69 + Zod 4.2 + `@hookform/resolvers 5.2`
- **UI:** Tailwind 4 + Radix UI primitives + ShadCN convention (`components/ui/`)
- **HTTP:** Axios 1.13 (interceptor'lu)
- **Realtime:** `@microsoft/signalr 10.0`
- **Markdown:** `react-markdown 10`, `remark-gfm 4`, `rehype-highlight 7`, `@uiw/react-md-editor 4`
- **Toast:** `sonner 2`
- **Icons:** `lucide-react 0.562`
- **Theme:** `next-themes 0.4`
- **SEO/JSON-LD:** `schema-dts 1.1`
- **Test:** Vitest 3.2

## Komutlar

```bash
npm run dev       # next dev
npm run build     # next build
npm run start     # next start
npm run lint      # eslint
npm test          # vitest run (one-shot)
npm run test:watch
```

## Klasor yapisi (gercek — `src/`)

```
app/
├── (public)/            # public sayfa grubu
├── dashboard/           # protected — kullanici alani
├── mrbekox-console/     # protected — admin alani
├── login/, register/
├── posts/[slug]/        # (gerekirse) — public grup icinde de olabilir
├── actions/             # server actions
├── globals.css
├── layout.tsx
├── icon.png
├── robots.ts
└── sitemap.ts
components/
├── admin/, auth/, posts/, comments/, layout/, home/, seo/
└── ui/                  # ShadCN primitives
hooks/                   # use* custom hooks
lib/
├── api.ts               # TEK Axios instance + interceptor + endpoint fonksiyonlari (rules'taki "lib/api/axios.ts + per-resource" GUNCEL DEGIL)
├── auth-events.ts
├── env.client.ts, env.server.ts, env.ts
├── file-validation.ts
├── geo-entities.ts
├── idempotency.ts       # Idempotency-Key helper
├── server-api.ts        # server-side fetch (RSC)
├── site-config.ts
├── utils.ts             # cn() + genel helper
├── validations.ts       # Zod schema'lar (lib/schemas/ degil)
└── __tests__/
stores/                  # Zustand store'lari (use{Domain}Store)
types/                   # global TS tipleri
```

> Eski rules dosyasi `lib/api/`, `lib/signalr/`, `lib/sanitize.ts`, `lib/schemas/` gibi yapilardan bahsediyor — **artik yoklar**. Gercek yapi yukarida.

## Naming

- Dosya: kebab-case (`edit-post-form.tsx`, `auth-store.ts`)
- Component: PascalCase
- Hook: `use*` prefix
- Store: `use{Domain}Store` (`usePostsStore`, `useAuthStore`)
- Type: PascalCase

## Zustand cache TTL pattern (5 dk + cacheVersion)

Yeni store eklerken bu sablon: TTL kontrolu + `cacheVersion` increment ile component refetch.

```typescript
const TTL_MS = 5 * 60 * 1000;
// data, cacheVersion, cachedAt, isLoading, fetch{X}, invalidate
```

Component'te: `useEffect(() => { fetch(); }, [cacheVersion, fetch]);`

## API client

- **Tek dosya:** `lib/api.ts` — Axios instance + interceptor (token inject, refresh, error map) + endpoint fonksiyonlari (postsApi, authApi, vb.)
- **`fetch` direkt cagirma** — daima `apiClient` veya `lib/server-api.ts` (RSC icin) uzerinden git.
- **Idempotency:** mutating call'larda `Idempotency-Key` header (uuid) ekle — backend bekliyor (`lib/idempotency.ts`).

## Form

- Schema: `lib/validations.ts` (Zod).
- Hook: `useForm({ resolver: zodResolver(schema) })`.
- Server-side validation FluentValidation'da otomatik calisir — frontend'de yeniden yazma.
- XSS sanitization: `lib/file-validation.ts` ve ilgili helper'lar.

## SignalR

- Hub'lar Api'de yalnizca `PublicCacheHub` (eski 3 hub gitti).
- Connection helper'i `lib/` icinde tek bir dosyada/utility'de — yeni hub eklenirse ayni dosyada genislet.

## Routing & Layout

- App Router gruplari: `(public)`, `dashboard`, `mrbekox-console` — protected ayri klasorler, parantez sadece public.
- Sayfa: `app/posts/[slug]/page.tsx` (server component default).
- `loading.tsx`, `error.tsx`, `not-found.tsx` — Next.js convention.
- Metadata API: `export const metadata: Metadata = { ... };` veya `generateMetadata`.

## UI/UX

- Toast: `sonner` → `toast.success/error`.
- Icon: `lucide-react`.
- Theme: `next-themes` (light/dark/system).
- ShadCN: `npx shadcn@latest add {name}` — manuel kopyalama yapma.

## Test

- Co-locate: `{file}.test.tsx` veya `__tests__/` (varsa) — bilesenle ayni klasor.
- `npm test` (run), `npm run test:watch` (watch).
- Mock: `vi.mock('@/lib/api', () => ({ ... }));`

## Performans

- Server Component varsayilan; `'use client'` sadece interaktivite/state.
- Image: `next/image` zorunlu (`width`, `height`, `alt`).
- Heavy client paketler: `dynamic(() => import('./X'), { ssr: false })`.

## Hatirlatma

- Backend hatasini `ApiResponse<T>.success/error` seklinde dondurur — interceptor bunu unwrap eder.
- Cache invalidation backend'ten gelirse SignalR `PublicCacheHub` event'i ile store'lari `invalidate()` et.
- Production env vars: `.env.local` (gitignore'lu) + `.env.example` referansi. Yeni env eklerken `env.client.ts`/`env.server.ts`'e tip ekle, runtime'da bos kalmasin.
