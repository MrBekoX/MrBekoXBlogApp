/**
 * Yayımlanmış yazar profili normalizasyonu (saf; /about sunucu bileşeni kullanır).
 *
 * Kaynak: backend GET /api/v1/profile (aktif + public + hash doğrulanmış profil;
 * no-store). Frontend profil verisinin AYRI kopyasını tutmaz; canonical
 * src/content/author-profile/profile.json bundle'a ALINMAZ.
 *
 * Güvenlik/tolerans kuralları:
 * - status 'public' değilse, kimlik/sürüm eksikse veya geçerli bölüm yoksa → null
 *   (sayfa biyografi gövdesi göstermeden "kullanılamıyor" bildirimi çizer).
 * - Bölüm kimliği /about anchor'ıdır; PROFILE_SECTION_ID_PATTERN dışı veya
 *   tekrarlı bölüm atılır (DOM id / citation bağlantısı güvenli kalır).
 * - İletişim kanalları yalnız mutlak http(s) URL ile kabul edilir.
 * - Alan adları camelCase beklenir; snake_case de toleranslı okunur.
 */

import type {
  AuthorProfile,
  AuthorProfileClaim,
  AuthorProfileContactChannel,
  AuthorProfileSection,
} from '@/types/profile';
import { PROFILE_SECTION_ID_PATTERN } from '@/lib/agent/citations';
import { hasControlOrSpace, safeExternalHttpUrl } from '@/lib/safe-url';

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function pick(source: Json, ...keys: string[]): unknown {
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null) return source[key];
  }
  return undefined;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
}

/** Başlık düz metin ya da {tr, en} sözlüğü olabilir; dil tercihine göre seçilir. */
function asTitle(value: unknown, language: string): string | null {
  if (typeof value === 'string') return value.trim() || null;
  if (isObject(value)) {
    const preferred = asString(value[language]) ?? asString(value.tr) ?? asString(value.en);
    if (preferred && preferred.trim()) return preferred.trim();
    for (const candidate of Object.values(value)) {
      if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
    }
  }
  return null;
}

function asRevision(value: unknown): number | null {
  const numeric = typeof value === 'string' && value.trim() !== '' ? Number(value) : value;
  return typeof numeric === 'number' && Number.isInteger(numeric) && numeric >= 0 ? numeric : null;
}

function normalizeClaim(value: unknown): AuthorProfileClaim | null {
  if (!isObject(value)) return null;
  return {
    asOf: asString(pick(value, 'asOf', 'as_of')),
    temporal: asString(value.temporal),
    status: asString(value.status),
  };
}

function normalizeSection(value: unknown, language: string): AuthorProfileSection | null {
  if (!isObject(value)) return null;
  const sectionId = asString(pick(value, 'sectionId', 'section_id'));
  if (!sectionId || !PROFILE_SECTION_ID_PATTERN.test(sectionId)) return null;

  const body = asString(value.body) ?? '';
  const notes = asStringList(value.notes);
  const headingPath = asStringList(pick(value, 'headingPath', 'heading_path'));
  const title = asTitle(value.title, language) ?? headingPath[headingPath.length - 1] ?? sectionId;
  if (!body.trim() && notes.length === 0) return null;

  return {
    sectionId,
    anchor: sectionId,
    kind: asString(value.kind) ?? 'bio',
    headingPath,
    title,
    body,
    notes,
    claim: normalizeClaim(value.claim),
  };
}

function normalizeChannel(value: unknown): AuthorProfileContactChannel | null {
  if (!isObject(value)) return null;
  const url = safeExternalHttpUrl(asString(value.url));
  if (!url) return null;
  const kind = asString(value.kind)?.trim() || 'link';
  const label = asString(value.label)?.trim() || kind;
  return { kind, label, url };
}

export function normalizeAuthorProfile(raw: unknown): AuthorProfile | null {
  if (!isObject(raw)) return null;

  const status = asString(raw.status);
  if (!status || status.trim().toLowerCase() !== 'public') return null;

  const profileId = asString(pick(raw, 'profileId', 'profile_id'));
  if (!profileId || profileId.includes(':') || hasControlOrSpace(profileId) || profileId.length > 128) {
    return null;
  }

  const revision = asRevision(raw.revision);
  const contentHash = asString(pick(raw, 'contentHash', 'content_hash'));
  if (revision === null || !contentHash) return null;

  const language = asString(raw.language) ?? 'tr';
  const rawSections = Array.isArray(raw.sections) ? raw.sections : [];
  const seen = new Set<string>();
  const sections: AuthorProfileSection[] = [];
  for (const candidate of rawSections) {
    const section = normalizeSection(candidate, language);
    if (!section || seen.has(section.sectionId)) continue;
    seen.add(section.sectionId);
    sections.push(section);
  }
  if (sections.length === 0) return null;

  const rawChannels = pick(raw, 'contactChannels', 'contact_channels');
  const contactChannels = (Array.isArray(rawChannels) ? rawChannels : [])
    .map(normalizeChannel)
    .filter((channel): channel is AuthorProfileContactChannel => channel !== null);

  return {
    profileId,
    revision,
    contentHash,
    language,
    ownerName: asString(pick(raw, 'ownerName', 'owner_name'))?.trim() || '',
    status: 'public',
    sections,
    contactChannels,
  };
}

/** Tarihli beyan ipucu: yalnız temporal=dated_snapshot ve geçerli as_of tarihi varsa. */
export function datedClaimAsOf(claim: AuthorProfileClaim | null | undefined): string | null {
  if (!claim || claim.temporal !== 'dated_snapshot' || !claim.asOf) return null;
  return /^\d{4}-\d{2}-\d{2}/.test(claim.asOf) ? claim.asOf.slice(0, 10) : null;
}

/** "2026-10-21" → "21 Ekim 2026" (UTC; geçersizse ham değer). */
export function formatProfileDate(isoDate: string, locale = 'tr-TR'): string {
  const date = new Date(`${isoDate.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return isoDate;
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(date);
}
