import React from 'react';
import { describe, expect, it } from 'vitest';
import { readMermaidChart } from './mermaid-source';

describe('readMermaidChart', () => {
  it('reads a mermaid fence and drops the markdown trailing newline', () => {
    const children = React.createElement(
      'code',
      { className: 'language-mermaid' },
      'flowchart TD\n  A-->B\n',
    );

    expect(readMermaidChart(children)).toBe('flowchart TD\n  A-->B');
  });

  it('joins highlighted token text inside a mermaid block', () => {
    const children = React.createElement(
      'code',
      { className: 'language-mermaid' },
      React.createElement('span', null, 'flowchart TD'),
      '\n',
      React.createElement('span', null, '  A-->B'),
    );

    expect(readMermaidChart(children)).toBe('flowchart TD\n  A-->B');
  });

  it('ignores the copy button sibling and other languages', () => {
    const children = [
      React.createElement('code', { className: 'language-typescript' }, 'const n = 1;\n'),
      React.createElement('div', { className: 'copied' }),
    ];

    expect(readMermaidChart(children)).toBeNull();
  });

  it('does not treat a longer language name as mermaid', () => {
    const children = React.createElement(
      'code',
      { className: 'language-mermaidjs' },
      'flowchart TD\n',
    );

    expect(readMermaidChart(children)).toBeNull();
  });
});
