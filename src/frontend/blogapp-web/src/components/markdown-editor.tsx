'use client';

import * as React from 'react';
import dynamic from 'next/dynamic';
import { useTheme } from 'next-themes';
import type { ExtraProps } from 'react-markdown';
import '@uiw/react-md-editor/markdown-editor.css';
import { MermaidDiagram } from '@/components/mermaid-diagram';
import { readMermaidChart } from '@/components/mermaid-source';

const MDEditor = dynamic(() => import('@uiw/react-md-editor'), { ssr: false });

function EditorPreviewPre({
  children,
  node,
  ...props
}: React.ComponentPropsWithoutRef<'pre'> & ExtraProps) {
  void node;
  const chart = readMermaidChart(children);
  if (chart !== null) {
    return <MermaidDiagram chart={chart} />;
  }

  return <pre {...props}>{children}</pre>;
}

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  height?: number;
}

export function MarkdownEditor({
  value,
  onChange,
  placeholder = 'Write your content in Markdown...',
  height = 400,
}: MarkdownEditorProps) {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  const previewOptions = React.useMemo(
    () => ({
      className: 'prose dark:prose-invert max-w-none',
      components: {
        pre: EditorPreviewPre,
      },
    }),
    [],
  );

  React.useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div
        className="animate-pulse bg-muted rounded-md"
        style={{ height }}
      />
    );
  }

  return (
    <div data-color-mode={resolvedTheme === 'dark' ? 'dark' : 'light'}>
      <MDEditor
        value={value}
        onChange={(val) => onChange(val || '')}
        height={height}
        preview="live"
        textareaProps={{
          placeholder,
        }}
        previewOptions={previewOptions}
      />
    </div>
  );
}

