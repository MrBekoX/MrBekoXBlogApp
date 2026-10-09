import * as React from 'react';

const MERMAID_LANGUAGE_CLASS = 'language-mermaid';

export function extractText(node: React.ReactNode): string {
  if (node == null || typeof node === 'boolean') {
    return '';
  }

  if (typeof node === 'string' || typeof node === 'number') {
    return String(node);
  }

  if (Array.isArray(node)) {
    return node.map((child) => extractText(child)).join('');
  }

  if (React.isValidElement<{ children?: React.ReactNode }>(node)) {
    return extractText(node.props.children);
  }

  return '';
}

function hasMermaidLanguage(className: string): boolean {
  return className.split(/\s+/).includes(MERMAID_LANGUAGE_CLASS);
}

/**
 * Returns the fenced mermaid source when the preview `pre` contains a
 * `language-mermaid` code block. Other code blocks return null so the
 * editor keeps its default highlighting.
 */
export function readMermaidChart(children: React.ReactNode): string | null {
  for (const child of React.Children.toArray(children)) {
    if (!React.isValidElement<{ className?: unknown; children?: React.ReactNode }>(child)) {
      continue;
    }

    const { className } = child.props;
    if (typeof className !== 'string' || !hasMermaidLanguage(className)) {
      continue;
    }

    return extractText(child.props.children).replace(/\n$/, '');
  }

  return null;
}
