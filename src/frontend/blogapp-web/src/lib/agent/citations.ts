/**
 * Agent kaynak kartı bağlantı çözümü (saf; SourceCard bunu render eder).
 *
 * - profile: YALNIZ url `^/about#<section>$` biçimindeyse ve `"/about#" + sectionId`
 *   ile birebir eşitse dahili /about bölüm bağlantısı. Makale slug'ına bağlanmaz;
 *   dış/eksik/uyumsuz URL bağlantısız metin olur.
 * - article: mevcut kural (sourceId "article:{id}#bolum" → /posts/{slug}#bolum);
 *   bölüm parçası URL-kodlanır. Slug yoksa (makalesiz panel) bağlantı üretilmez.
 * - web: yalnız mutlak http(s) URL dış bağlantı; aksi halde bağlantısız metin.
 * - bilinmeyen tür: bağlantısız metin.
 */

import type { AgentRunCitation } from '@/types/agent';
import { safeExternalHttpUrl } from '@/lib/safe-url';

/** Profil bölüm kimliği = /about anchor'ı (decisions K2/K3). */
export const PROFILE_SECTION_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,127}$/;
const PROFILE_URL_PATTERN = /^\/about#[a-z0-9][a-z0-9-]{0,127}$/;

export type CitationLink =
  | { type: 'profile'; href: string; title: string | null; sectionId: string }
  | { type: 'article'; href: string; title: string | null; section: string | null }
  | { type: 'external'; href: string; title: string | null }
  | { type: 'text'; kind: string; title: string | null; detail: string | null };

function cleanTitle(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed.slice(0, 300) : null;
}

/** Profil citation'ının güvenli /about bağlantısı; uyumsuzsa null. */
export function profileCitationHref(citation: Pick<AgentRunCitation, 'url' | 'sectionId'>): string | null {
  const sectionId = typeof citation.sectionId === 'string' ? citation.sectionId : '';
  const url = typeof citation.url === 'string' ? citation.url : '';
  if (!PROFILE_SECTION_ID_PATTERN.test(sectionId)) return null;
  if (!PROFILE_URL_PATTERN.test(url)) return null;
  const expected = `/about#${sectionId}`;
  return url === expected ? expected : null;
}

/** Makale citation'ının sourceId'sinden bölüm anchor'ı ("article:{id}#bolum"). */
export function articleCitationSection(sourceId: string | null | undefined): string | null {
  if (typeof sourceId !== 'string') return null;
  const hashIndex = sourceId.indexOf('#');
  if (hashIndex < 0) return null;
  const section = sourceId.slice(hashIndex + 1).split('#')[0];
  return section.length > 0 ? section : null;
}

export function resolveCitationLink(
  citation: AgentRunCitation,
  context: { articleSlug?: string | null } = {},
): CitationLink {
  const title = cleanTitle(citation.title);

  if (citation.kind === 'profile') {
    const href = profileCitationHref(citation);
    if (href) {
      return { type: 'profile', href, title, sectionId: citation.sectionId as string };
    }
    return { type: 'text', kind: 'profile', title, detail: null };
  }

  if (citation.kind === 'article') {
    const section = articleCitationSection(citation.sourceId);
    const slug = typeof context.articleSlug === 'string' ? context.articleSlug : '';
    if (!slug) {
      return { type: 'text', kind: 'article', title, detail: section ? `#${section}` : null };
    }
    const href = section ? `/posts/${slug}#${encodeURIComponent(section)}` : `/posts/${slug}`;
    return { type: 'article', href, title, section };
  }

  if (citation.kind === 'web') {
    const href = safeExternalHttpUrl(citation.url);
    if (href) return { type: 'external', href, title };
    return { type: 'text', kind: 'web', title, detail: null };
  }

  return { type: 'text', kind: String(citation.kind ?? 'unknown'), title, detail: null };
}
