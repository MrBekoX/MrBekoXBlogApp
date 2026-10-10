import { describe, expect, it } from 'vitest';
import { postSearchDescription, postSearchTitle, speakableSelectors } from './seo-text';

describe('post search text', () => {
  it('prefers the editor meta title and description', () => {
    expect(postSearchTitle({ title: 'Ham başlık', metaTitle: '  SEO başlık  ' })).toBe('SEO başlık');
    expect(
      postSearchDescription({
        metaDescription: 'Kısa özet',
        excerpt: 'Excerpt',
        content: '# İçerik',
      }),
    ).toBe('Kısa özet');
  });

  it('strips markdown when falling back to the article body', () => {
    expect(
      postSearchDescription({
        content: '# Başlık\n\n**kalın** bir paragraf.',
      }),
    ).toBe('Başlık kalın bir paragraf.');
  });
});

describe('speakableSelectors', () => {
  it('names the excerpt selector only when that element is rendered', () => {
    expect(speakableSelectors(false)).toEqual(['.post-title']);
    expect(speakableSelectors(true)).toEqual(['.post-title', '.post-excerpt']);
  });
});
