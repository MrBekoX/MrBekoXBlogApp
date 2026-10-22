import { describe, expect, it } from 'vitest';
import { datedClaimAsOf, formatProfileDate, normalizeAuthorProfile } from './author-profile';

function apiProfile(overrides: Record<string, unknown> = {}) {
  return {
    profileId: 'berkay-kaplan',
    revision: 1,
    contentHash: '4f3b02e187c2b8c04134aa2c80df4b2d8c817377780aca74d2a11e9bf0c1406d',
    language: 'tr',
    ownerName: 'Berkay Kaplan',
    status: 'public',
    sections: [
      {
        sectionId: 'overview',
        anchor: 'overview',
        kind: 'bio',
        headingPath: ['Kısaca'],
        title: 'Kısaca',
        body: 'Ben Berkay Kaplan.',
        notes: [],
        claim: { asOf: '2026-10-21', temporal: 'current_at_source' },
      },
      {
        sectionId: 'ai-root-agent',
        anchor: 'ai-root-agent',
        kind: 'ai_work',
        headingPath: ['Yapay zekâ ve ajan çalışmalarım', 'Root Agent'],
        title: 'Root Agent',
        body: 'Root Agent ...',
        notes: ['Sürüm ve test durumu tarihli beyandır.'],
        claim: { asOf: '2026-10-21', temporal: 'dated_snapshot', status: 'published' },
      },
    ],
    contactChannels: [
      { kind: 'github', label: 'GitHub', url: 'https://github.com/MrBekoX' },
      { kind: 'x', label: 'X', url: 'javascript:alert(1)' },
    ],
    ...overrides,
  };
}

describe('normalizeAuthorProfile', () => {
  it('geçerli public profili normalize eder; güvensiz iletişim kanalını atar', () => {
    const profile = normalizeAuthorProfile(apiProfile());
    expect(profile).not.toBeNull();
    expect(profile?.profileId).toBe('berkay-kaplan');
    expect(profile?.revision).toBe(1);
    expect(profile?.sections.map((section) => section.sectionId)).toEqual(['overview', 'ai-root-agent']);
    expect(profile?.sections[1].notes).toEqual(['Sürüm ve test durumu tarihli beyandır.']);
    expect(profile?.contactChannels).toEqual([{ kind: 'github', label: 'GitHub', url: 'https://github.com/MrBekoX' }]);
  });

  it.each([
    ['null (503 / ağ hatası)', null],
    ['public olmayan durum', apiProfile({ status: 'draft' })],
    ['durum yok', apiProfile({ status: undefined })],
    ['kimlik yok', apiProfile({ profileId: '' })],
    ['ayraçlı kimlik', apiProfile({ profileId: 'a:b' })],
    ['sürüm yok', apiProfile({ revision: undefined })],
    ['hash yok', apiProfile({ contentHash: '' })],
    ['bölüm yok', apiProfile({ sections: [] })],
  ])('kullanılamaz: %s → null (biyografi gövdesi render edilmez)', (_label, raw) => {
    expect(normalizeAuthorProfile(raw)).toBeNull();
  });

  it('geçersiz/tekrarlı bölüm kimlikleri atılır (DOM id ve anchor güvenliği)', () => {
    const base = apiProfile();
    const profile = normalizeAuthorProfile({
      ...base,
      sections: [
        ...base.sections,
        { ...base.sections[0] },
        { ...base.sections[0], sectionId: 'Bad Id' },
        { ...base.sections[0], sectionId: '"><script>' },
        { ...base.sections[0], sectionId: 'empty-body', body: '', notes: [] },
      ],
    });
    expect(profile?.sections.map((section) => section.sectionId)).toEqual(['overview', 'ai-root-agent']);
  });

  it('snake_case alanları ve {tr,en} başlığı toleranslı okunur', () => {
    const profile = normalizeAuthorProfile({
      profile_id: 'berkay-kaplan',
      revision: '2',
      content_hash: 'abc',
      language: 'tr',
      owner_name: 'Berkay Kaplan',
      status: 'PUBLIC',
      sections: [
        {
          section_id: 'education',
          heading_path: ['Eğitim ve kariyer yolum', 'Eğitim'],
          title: { tr: 'Eğitim', en: 'Education' },
          body: '- **Eğitim:** ...',
          notes: [],
          claim: { as_of: '2026-10-21', temporal: 'historical' },
        },
      ],
      contact_channels: [{ kind: 'website', label: 'Web sitesi', url: 'https://mrbekox.dev' }],
    });
    expect(profile?.revision).toBe(2);
    expect(profile?.sections[0]).toMatchObject({ sectionId: 'education', anchor: 'education', title: 'Eğitim' });
    expect(profile?.sections[0].claim?.asOf).toBe('2026-10-21');
    expect(profile?.contactChannels[0].url).toBe('https://mrbekox.dev/');
  });
});

describe('dated claim hints', () => {
  it('yalnız dated_snapshot için tarih ipucu', () => {
    expect(datedClaimAsOf({ asOf: '2026-10-21', temporal: 'dated_snapshot' })).toBe('2026-10-21');
    expect(datedClaimAsOf({ asOf: '2026-10-21', temporal: 'current_at_source' })).toBeNull();
    expect(datedClaimAsOf({ asOf: 'yakında', temporal: 'dated_snapshot' })).toBeNull();
    expect(datedClaimAsOf(null)).toBeNull();
  });

  it('tarih biçimi (UTC, tr-TR)', () => {
    expect(formatProfileDate('2026-10-21')).toBe('21 Ekim 2026');
    expect(formatProfileDate('nope')).toBe('nope');
  });
});
