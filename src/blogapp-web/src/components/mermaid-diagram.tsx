'use client';

import * as React from 'react';
import { useTheme } from 'next-themes';

type MermaidTheme = 'dark' | 'default';

let renderQueue: Promise<unknown> = Promise.resolve();
let activeTheme: MermaidTheme | null = null;

function enqueueRender<T>(task: () => Promise<T>): Promise<T> {
  const run = renderQueue.then(task, task);
  renderQueue = run.then(
    () => undefined,
    () => undefined,
  );
  return run;
}

async function loadMermaid(theme: MermaidTheme) {
  const { default: mermaid } = await import('mermaid');

  if (activeTheme !== theme) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      suppressErrorRendering: true,
      theme,
    });
    mermaid.parseError = () => undefined;
    activeTheme = theme;
  }

  return mermaid;
}

function diagramErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message.split('\n')[0] ?? 'Mermaid diyagramı çizilemedi.';
  }

  return 'Mermaid diyagramı çizilemedi.';
}

interface MermaidDiagramProps {
  chart: string;
}

export function MermaidDiagram({ chart }: MermaidDiagramProps) {
  const { resolvedTheme } = useTheme();
  const theme: MermaidTheme = resolvedTheme === 'dark' ? 'dark' : 'default';
  const baseId = React.useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const [svg, setSvg] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!chart.trim()) {
      setSvg(null);
      setError(null);
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(() => {
      void enqueueRender(async () => {
        try {
          const mermaid = await loadMermaid(theme);
          await mermaid.parse(chart);
          if (cancelled) return;

          const renderId = `mermaid-${baseId}-${Date.now()}`;
          const result = await mermaid.render(renderId, chart);
          if (cancelled) return;

          setSvg(result.svg);
          setError(null);
        } catch (renderError) {
          if (cancelled) return;
          setSvg(null);
          setError(diagramErrorMessage(renderError));
        }
      });
    }, 300);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [baseId, chart, theme]);

  if (!chart.trim()) {
    return (
      <p className="not-prose my-3 text-sm text-muted-foreground">
        Mermaid bloğu boş.
      </p>
    );
  }

  if (error) {
    return (
      <div
        className="not-prose my-3 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
        role="status"
      >
        Mermaid diyagramı çizilemedi. {error}
      </div>
    );
  }

  if (!svg) {
    return (
      <div
        className="not-prose my-3 h-24 animate-pulse rounded-md bg-muted"
        aria-hidden
      />
    );
  }

  return (
    <div
      className="not-prose my-3 overflow-x-auto rounded-md border border-border bg-background p-3 [&_svg]:h-auto [&_svg]:max-w-full"
      role="img"
      aria-label="Mermaid diyagramı"
      data-mermaid-rendered="true"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
