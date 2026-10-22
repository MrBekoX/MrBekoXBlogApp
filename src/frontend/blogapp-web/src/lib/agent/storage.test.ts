import { describe, expect, it } from 'vitest';
import {
  articleRunStorageKey,
  clearStoredRunId,
  isValidRunId,
  legacyArticleRunStorageKey,
  migrateLegacyArticleRun,
  profileRunStorageKey,
  readStoredRunId,
  writeStoredRunId,
  type StorageLike,
} from './storage';

class MemoryStorage implements StorageLike {
  readonly map = new Map<string, string>();
  getItem(key: string): string | null {
    return this.map.has(key) ? (this.map.get(key) as string) : null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
}

const ARTICLE = '1aaaaaaa-0000-4000-8000-000000000001';
const RUN_A = '11111111-1111-4111-8111-111111111111';
const RUN_B = '22222222-2222-4222-8222-222222222222';

describe('storage keys', () => {
  it('makale anahtarı konu başına ayrıdır', () => {
    expect(articleRunStorageKey(ARTICLE, 'auto')).toBe(`agent-run:v2:article:${ARTICLE}:auto`);
    expect(articleRunStorageKey(ARTICLE, 'who_am_i')).toBe(`agent-run:v2:article:${ARTICLE}:who_am_i`);
    expect(articleRunStorageKey(ARTICLE, 'auto')).not.toBe(articleRunStorageKey(ARTICLE, 'who_am_i'));
  });

  it('profil anahtarı makale anahtarından ayrıdır', () => {
    expect(profileRunStorageKey('berkay-kaplan')).toBe('agent-run:v2:profile:berkay-kaplan:who_am_i');
  });

  it('articleId undefined/boş/sahte ayraçlı ise anahtar ÜRETİLMEZ', () => {
    expect(() => articleRunStorageKey(undefined as unknown as string, 'auto')).toThrow();
    expect(() => articleRunStorageKey('', 'auto')).toThrow();
    expect(() => articleRunStorageKey('a:b', 'auto')).toThrow();
    expect(() => articleRunStorageKey('a b', 'auto')).toThrow();
    expect(() => profileRunStorageKey('')).toThrow();
  });

  it('eski anahtar biçimi korunur (yalnız geçiş için)', () => {
    expect(legacyArticleRunStorageKey(ARTICLE)).toBe(`agent-run:${ARTICLE}`);
  });
});

describe('migrateLegacyArticleRun', () => {
  it('eski kaydı auto anahtarına taşır ve eski anahtarı siler (tek seferlik)', () => {
    const storage = new MemoryStorage();
    storage.setItem(`agent-run:${ARTICLE}`, RUN_A);

    expect(migrateLegacyArticleRun(storage, ARTICLE)).toBe(RUN_A);
    expect(storage.getItem(`agent-run:v2:article:${ARTICLE}:auto`)).toBe(RUN_A);
    expect(storage.getItem(`agent-run:${ARTICLE}`)).toBeNull();
    // who_am_i anahtarına ASLA taşınmaz
    expect(storage.getItem(`agent-run:v2:article:${ARTICLE}:who_am_i`)).toBeNull();

    // ikinci çağrı no-op
    expect(migrateLegacyArticleRun(storage, ARTICLE)).toBeNull();
    expect(storage.getItem(`agent-run:v2:article:${ARTICLE}:auto`)).toBe(RUN_A);
  });

  it('yeni anahtar doluysa eski değer daha yeni kaydı ezmez ama yine silinir', () => {
    const storage = new MemoryStorage();
    storage.setItem(`agent-run:${ARTICLE}`, RUN_A);
    storage.setItem(`agent-run:v2:article:${ARTICLE}:auto`, RUN_B);

    expect(migrateLegacyArticleRun(storage, ARTICLE)).toBeNull();
    expect(storage.getItem(`agent-run:v2:article:${ARTICLE}:auto`)).toBe(RUN_B);
    expect(storage.getItem(`agent-run:${ARTICLE}`)).toBeNull();
  });

  it('biçim dışı eski değer taşınmaz, silinir', () => {
    const storage = new MemoryStorage();
    storage.setItem(`agent-run:${ARTICLE}`, '../../posts');
    expect(migrateLegacyArticleRun(storage, ARTICLE)).toBeNull();
    expect(storage.map.size).toBe(0);
  });

  it('başka makalenin eski kaydına dokunmaz', () => {
    const storage = new MemoryStorage();
    storage.setItem('agent-run:other-article', RUN_A);
    expect(migrateLegacyArticleRun(storage, ARTICLE)).toBeNull();
    expect(storage.getItem('agent-run:other-article')).toBe(RUN_A);
  });

  it('depolama hata verirse güvenle null döner', () => {
    const broken: StorageLike = {
      getItem: () => {
        throw new Error('SecurityError');
      },
      setItem: () => undefined,
      removeItem: () => undefined,
    };
    expect(migrateLegacyArticleRun(broken, ARTICLE)).toBeNull();
  });
});

describe('read/write/clear', () => {
  it('geçerli kimliği yazar/okur; biçim dışı değeri siler', () => {
    const storage = new MemoryStorage();
    const key = profileRunStorageKey('berkay-kaplan');
    writeStoredRunId(storage, key, RUN_A);
    expect(readStoredRunId(storage, key)).toBe(RUN_A);

    storage.setItem(key, 'bad/value');
    expect(readStoredRunId(storage, key)).toBeNull();
    expect(storage.getItem(key)).toBeNull();

    writeStoredRunId(storage, key, 'x/../y');
    expect(storage.getItem(key)).toBeNull();
  });

  it('clear yalnız beklenen run hâlâ kayıtlıysa siler (yarış güvenli)', () => {
    const storage = new MemoryStorage();
    const key = articleRunStorageKey(ARTICLE, 'auto');
    storage.setItem(key, RUN_B);
    clearStoredRunId(storage, key, RUN_A); // eski run'ın temizliği yeni kaydı silmez
    expect(storage.getItem(key)).toBe(RUN_B);
    clearStoredRunId(storage, key, RUN_B);
    expect(storage.getItem(key)).toBeNull();
  });

  it('isValidRunId', () => {
    expect(isValidRunId(RUN_A)).toBe(true);
    expect(isValidRunId('')).toBe(false);
    expect(isValidRunId('a/b')).toBe(false);
    expect(isValidRunId(42)).toBe(false);
  });
});
