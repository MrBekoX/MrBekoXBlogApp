'use client';

import * as React from 'react';
import { useTheme } from 'next-themes';

function newChannelToken(): string {
  return [...crypto.getRandomValues(new Uint8Array(16))].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** Rendering runs in a disposable opaque-origin document; chart CSS never enters this page. */
export function MermaidDiagram({ chart }: { chart: string }) {
  const { resolvedTheme } = useTheme();
  const theme = resolvedTheme === 'dark' ? 'dark' : 'default';
  const frame = React.useRef<HTMLIFrameElement>(null);
  const [channel, setChannel] = React.useState<string | null>(null);
  const [svg, setSvg] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!chart.trim()) { setChannel(null); setSvg(null); setError(null); return; }
    const token = newChannelToken();
    let timeout: ReturnType<typeof setTimeout>;
    const finish = () => {
      clearTimeout(timeout);
      window.removeEventListener('message', receive);
      setChannel(null); // Release the heavy renderer immediately after each result.
    };
    const receive = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || !event.data || event.data.token !== token) return;
      if (event.data.type === 'mermaid:ready') {
        frame.current?.contentWindow?.postMessage({ type: 'mermaid:render', token, chart, theme }, '*');
      } else if (event.data.type === 'mermaid:result') {
        const rendered = event.data.svg;
        if (typeof rendered !== 'string' || rendered.length > 10 * 1024 * 1024 || !/^<svg[\s>]/i.test(rendered.trim())) {
          setError('Geçersiz diyagram çıktısı.'); setSvg(null);
        } else { setSvg(rendered); setError(null); }
        finish();
      } else if (event.data.type === 'mermaid:error') {
        setError(typeof event.data.message === 'string' ? event.data.message.slice(0, 400) : 'Diyagram çizilemedi.');
        setSvg(null); finish();
      }
    };
    window.addEventListener('message', receive);
    const debounce = setTimeout(() => {
      setChannel(token);
      timeout = setTimeout(() => { setError('Diyagram çizimi zaman aşımına uğradı.'); setSvg(null); finish(); }, 30000);
    }, 300);
    return () => { clearTimeout(debounce); clearTimeout(timeout); window.removeEventListener('message', receive); };
  }, [chart, theme]);

  return (
    <div className="not-prose relative my-3 overflow-x-auto rounded-md border border-border bg-background p-3">
      {channel && <iframe key={channel} ref={frame} src={'/mermaid-renderer#' + channel} sandbox="allow-scripts" referrerPolicy="no-referrer" title="Yalıtılmış diyagram çizicisi" aria-hidden tabIndex={-1} className="pointer-events-none absolute h-px w-px border-0 opacity-0" />}
      {!chart.trim() ? <p className="text-sm text-muted-foreground">Mermaid bloğu boş.</p>
        : error ? <p role="status" className="text-sm text-destructive">Mermaid diyagramı çizilemedi. {error}</p>
          : svg ? <div role="img" aria-label="Mermaid diyagramı" data-mermaid-rendered="true">
            {/* SVG image context cannot execute chart scripts or affect parent styles. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)} alt="Mermaid diyagramı" className="h-auto max-w-full" />
          </div> : <div className="h-24 animate-pulse rounded-md bg-muted" aria-hidden />}
    </div>
  );
}
