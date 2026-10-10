import { describe, expect, it } from 'vitest';
import { extractFAQFromContent } from './faq-schema';

describe('extractFAQFromContent', () => {
  it('keeps a heading that is already a question', () => {
    const content = [
      '## CQRS nedir?',
      '',
      'Komut ve sorgu sorumluluklarını ayıran bir desendir.',
    ].join('\n');

    expect(extractFAQFromContent(content)).toEqual([
      {
        question: 'CQRS nedir?',
        answer: 'Komut ve sorgu sorumluluklarını ayıran bir desendir.',
      },
    ]);
  });

  it('does not invent a question from an ordinary heading', () => {
    const content = [
      '## Kurulum',
      '',
      'Projeyi yerelde ayağa kaldırmak için aşağıdaki adımları izleyin.',
    ].join('\n');

    expect(extractFAQFromContent(content)).toEqual([]);
  });
});
