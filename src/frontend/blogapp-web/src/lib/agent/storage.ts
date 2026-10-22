/**
 * Agent run kalıcılık anahtarları ve eski anahtar geçişi (saf; Storage enjekte edilir).
 *
 * Anahtarlar (decisions K7):
 *   agent-run:v2:article:{articleId}:{topic}   — makale paneli, konu başına ayrı
 *   agent-run:v2:profile:{profileId}:who_am_i  — /about profil paneli
 * Eski anahtar `agent-run:{articleId}` (konu öncesi; hepsi 'auto') yalnız BİR KEZ
 * okunur → auto anahtarına taşınır → silinir. Yeni anahtar zaten doluysa eski
 * değer yeni kaydı EZMEZ (daha yeni çalışma korunur), yine de silinir.
 *
 * Saklanan değer yalnız run kimliğidir; konu/sahiplik doğrulaması geri yüklemede
 * backend GET ile yapılır (restore.ts). Kimlik biçimi dışı değer okunmaz ve silinir.
 */

import type { AgentConversationTopic } from '@/types/agent';
import { hasControlOrSpace } from '@/lib/safe-url';

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const KEY_PREFIX = 'agent-run:v2';
const LEGACY_PREFIX = 'agent-run:';

/** Run kimliği biçimi (GUID ve benzeri güvenli karakterler; yol ayracı yok). */
const RUN_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;
function assertSegment(value: string | null | undefined, name: string): string {
  // Anahtar segmenti: boş, ":" içeren veya boşluk/kontrol karakterli kimlik kabul edilmez.
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 256 ||
    value.includes(':') ||
    hasControlOrSpace(value)
  ) {
    throw new Error(`invalid ${name} for agent storage key`);
  }
  return value;
}

export function isValidRunId(value: unknown): value is string {
  return typeof value === 'string' && RUN_ID_PATTERN.test(value);
}

/** Makale paneli anahtarı. articleId boş/undefined ise HATA fırlatır (sahte kimlik yok). */
export function articleRunStorageKey(articleId: string, topic: AgentConversationTopic): string {
  return `${KEY_PREFIX}:article:${assertSegment(articleId, 'articleId')}:${topic === 'who_am_i' ? 'who_am_i' : 'auto'}`;
}

/** /about profil paneli anahtarı (konu her zaman who_am_i). */
export function profileRunStorageKey(profileId: string): string {
  return `${KEY_PREFIX}:profile:${assertSegment(profileId, 'profileId')}:who_am_i`;
}

/** Konu öncesi eski anahtar (yalnız geçiş için okunur). */
export function legacyArticleRunStorageKey(articleId: string): string {
  return `${LEGACY_PREFIX}${assertSegment(articleId, 'articleId')}`;
}

/**
 * Eski `agent-run:{articleId}` kaydını tek seferlik auto anahtarına taşır.
 * Dönüş: taşınan run kimliği (yoksa/geçersizse ya da yeni anahtar doluysa null).
 * Eski anahtar her durumda silinir (ikinci çağrı no-op'tur).
 */
export function migrateLegacyArticleRun(storage: StorageLike, articleId: string): string | null {
  const legacyKey = legacyArticleRunStorageKey(articleId);
  let legacyValue: string | null;
  try {
    legacyValue = storage.getItem(legacyKey);
  } catch {
    return null;
  }
  if (legacyValue === null) return null;

  try {
    storage.removeItem(legacyKey);
  } catch {
    // silinemese de taşıma denenir; bir sonraki çağrı yeniden dener
  }

  if (!isValidRunId(legacyValue)) return null;

  const targetKey = articleRunStorageKey(articleId, 'auto');
  try {
    if (storage.getItem(targetKey) !== null) return null; // daha yeni kayıt korunur
    storage.setItem(targetKey, legacyValue);
    return legacyValue;
  } catch {
    return null;
  }
}

/** Kayıtlı run kimliğini okur; biçim dışı değer silinir ve null döner. */
export function readStoredRunId(storage: StorageLike, key: string): string | null {
  let value: string | null;
  try {
    value = storage.getItem(key);
  } catch {
    return null;
  }
  if (value === null) return null;
  if (!isValidRunId(value)) {
    try {
      storage.removeItem(key);
    } catch {
      // yok say
    }
    return null;
  }
  return value;
}

export function writeStoredRunId(storage: StorageLike, key: string, runId: string): void {
  if (!isValidRunId(runId)) return;
  try {
    storage.setItem(key, runId);
  } catch {
    // kota/gizli mod: kalıcılık yalnız kolaylıktır
  }
}

/** Anahtarı yalnız hâlâ beklenen run'ı gösteriyorsa siler (yarış güvenli). */
export function clearStoredRunId(storage: StorageLike, key: string, expectedRunId?: string): void {
  try {
    if (expectedRunId !== undefined && storage.getItem(key) !== expectedRunId) return;
    storage.removeItem(key);
  } catch {
    // yok say
  }
}

/** Tarayıcı localStorage'ı (erişim engelliyse null). */
export function getBrowserStorage(): StorageLike | null {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null;
  }
}
