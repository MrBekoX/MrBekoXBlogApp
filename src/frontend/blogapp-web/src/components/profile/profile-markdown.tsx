/**
 * Profil bölüm gövdesi markdown görünümü (sunucu bileşeni; istemci JS'i yok).
 *
 * react-markdown + remark-gfm; raw HTML yok (rehype-raw YOK). Linkler
 * safeChatLinkHref ile daraltılır (yalnız http(s), kök-göreli, #anchor; dış
 * bağlantı yeni sekme + rel="noopener noreferrer nofollow"); görseller
 * yüklenmez (alt metin gösterilir). Bölüm içi başlıklar sayfa hiyerarşisini
 * bozmasın diye h4 ve altına indirilir.
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { safeChatLinkHref } from '@/lib/safe-url';

export function ProfileMarkdown({ content }: { content: string }) {
  return (
    <div className="space-y-2 text-sm leading-relaxed text-gray-300">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
          li: ({ children }) => <li>{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-gray-100">{children}</strong>,
          h1: ({ children }) => <h4 className="mt-3 mb-1 text-sm font-semibold text-white">{children}</h4>,
          h2: ({ children }) => <h4 className="mt-3 mb-1 text-sm font-semibold text-white">{children}</h4>,
          h3: ({ children }) => <h4 className="mt-3 mb-1 text-sm font-semibold text-white">{children}</h4>,
          h4: ({ children }) => <h5 className="mt-2 mb-1 text-xs font-semibold text-white">{children}</h5>,
          h5: ({ children }) => <h6 className="mt-2 mb-1 text-xs font-semibold text-gray-200">{children}</h6>,
          h6: ({ children }) => <h6 className="mt-2 mb-1 text-xs font-semibold text-gray-200">{children}</h6>,
          code: ({ children }) => (
            <code className="rounded border border-ide-border bg-black/40 px-1 py-0.5 text-[0.85em] text-ide-primary">
              {children}
            </code>
          ),
          img: ({ alt }) => (alt ? <span>{alt}</span> : null),
          a: ({ href, children }) => {
            const safe = safeChatLinkHref(href);
            if (!safe) return <span>{children}</span>;
            return safe.external ? (
              <a
                href={safe.href}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="text-ide-primary underline underline-offset-2 hover:opacity-80"
              >
                {children}
              </a>
            ) : (
              <a href={safe.href} className="text-ide-primary underline underline-offset-2 hover:opacity-80">
                {children}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
