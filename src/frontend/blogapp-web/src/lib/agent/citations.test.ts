import { describe, expect, it } from 'vitest';
import type { AgentRunCitation } from '@/types/agent';
import { articleCitationSection, profileCitationHref, resolveCitationLink } from './citations';

function profileCitation(overrides: Partial<AgentRunCitation> = {}): AgentRunCitation {
  return {
    kind: 'profile',
    title: 'Eğitim',
    url: '/about#education',
    sourceId: 'profile:berkay-kaplan:1:4f3b02e1:education:0',
    profileId: 'berkay-kaplan',
    profileRevision: 1,
    profileContentHash: '4f3b02e1',
    sectionId: 'education',
    chunkIndex: 0,
    ...overrides,
  };
}

describe('profile citation', () => {
  it('geçerli url + sectionId → dahili /about#bölüm bağlantısı', () => {
    expect(resolveCitationLink(profileCitation(), { articleSlug: 'bir-yazi' })).toEqual({
      type: 'profile',
      href: '/about#education',
      title: 'Eğitim',
      sectionId: 'education',
    });
  });

  it('makale slug’ına ASLA bağlanmaz', () => {
    const link = resolveCitationLink(profileCitation(), { articleSlug: 'bir-yazi' });
    expect(link.type === 'profile' && link.href.includes('/posts/')).toBe(false);
  });

  it.each([
    ['dış profil URL', { url: 'https://evil.example/about#education' }],
    ['protokol-göreli', { url: '//evil.example/about#education' }],
    ['javascript şeması', { url: 'javascript:alert(1)//#education' }],
    ['url sectionId ile eşleşmez', { url: '/about#teaching' }],
    ['büyük harfli anchor', { url: '/about#Education', sectionId: 'Education' }],
    ['anchor içinde HTML', { url: '/about#<img>', sectionId: '<img>' }],
    ['sectionId yok', { sectionId: null }],
    ['url yok', { url: null }],
    ['ek yol', { url: '/about/x#education' }],
    ['ek sorgu', { url: '/about?x=1#education' }],
  ])('%s → bağlantısız metin', (_label, overrides) => {
    const link = resolveCitationLink(profileCitation(overrides as Partial<AgentRunCitation>));
    expect(link.type).toBe('text');
    expect(profileCitationHref(profileCitation(overrides as Partial<AgentRunCitation>))).toBeNull();
  });

  it('128 karakteri aşan bölüm kimliği reddedilir', () => {
    const long = `a${'b'.repeat(128)}`;
    expect(profileCitationHref({ url: `/about#${long}`, sectionId: long })).toBeNull();
  });
});

describe('article citation', () => {
  it('sourceId bölümünden /posts/{slug}#bölüm üretir', () => {
    expect(
      resolveCitationLink(
        { kind: 'article', title: 'B10 makale', sourceId: 'article:1a#giris' },
        { articleSlug: 'b10-makale' },
      ),
    ).toEqual({ type: 'article', href: '/posts/b10-makale#giris', title: 'B10 makale', section: 'giris' });
  });

  it('bölüm parçası URL-kodlanır', () => {
    const link = resolveCitationLink(
      { kind: 'article', sourceId: 'article:1a#bölüm "x"<y>' },
      { articleSlug: 'yazi' },
    );
    expect(link).toMatchObject({ type: 'article', href: `/posts/yazi#${encodeURIComponent('bölüm "x"<y>')}` });
  });

  it('bölümsüz kaynak makale köküne gider', () => {
    expect(resolveCitationLink({ kind: 'article', sourceId: 'article:1a' }, { articleSlug: 'yazi' })).toMatchObject({
      href: '/posts/yazi',
      section: null,
    });
  });

  it('slug yoksa (makalesiz panel) bağlantı uydurulmaz', () => {
    expect(resolveCitationLink({ kind: 'article', sourceId: 'article:1a#giris' }).type).toBe('text');
  });

  it('articleCitationSection', () => {
    expect(articleCitationSection('article:1#a')).toBe('a');
    expect(articleCitationSection('article:1#')).toBeNull();
    expect(articleCitationSection(null)).toBeNull();
  });
});

describe('web citation', () => {
  it('yalnız http(s) dış bağlantı', () => {
    expect(resolveCitationLink({ kind: 'web', title: 'Docs', url: 'https://learn.microsoft.com/x' })).toEqual({
      type: 'external',
      href: 'https://learn.microsoft.com/x',
      title: 'Docs',
    });
  });

  it.each(['javascript:alert(1)', 'data:text/html,x', '//evil.example', '/about#x', 'mailto:a@b.c', null])(
    '%s → bağlantısız metin',
    (url) => {
      expect(resolveCitationLink({ kind: 'web', url }).type).toBe('text');
    },
  );
});

describe('unknown kind', () => {
  it('bilinmeyen tür bağlantısız metindir', () => {
    expect(resolveCitationLink({ kind: 'mystery', url: 'https://example.com' })).toMatchObject({
      type: 'text',
      kind: 'mystery',
    });
  });
});
