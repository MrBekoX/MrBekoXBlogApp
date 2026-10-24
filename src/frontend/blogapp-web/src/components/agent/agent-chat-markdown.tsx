'use client';

/**
 * Agent sohbet yanıtı markdown görünümü. Makale sayfasıyla AYNI zincir:
 * react-markdown + remark-gfm + rehype-highlight (package.json bağımlıları;
 * yeni paket eklenmedi). Raw HTML kaçırılır (rehype-raw YOK); react-markdown'ın
 * varsayılan URL transformu javascript:/data: şemalarını eler. Linkler ayrıca
 * safeChatLinkHref ile daraltılır: yalnız http(s), kök-göreli ("/…") ve "#…";
 * dış link yeni sekmede rel="noopener noreferrer nofollow"; diğerleri düz metin.
 * hljs-* token renkleri için küçük, bileşenle sınırlı koyu tema — site tasarım
 * diliyle (IDE paleti: amber primary, slate gri tonları) uyumlu; kapsamlı stiller
 * globals.css üzerinden harici CSS olarak yüklenir.
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { safeChatLinkHref } from '@/lib/safe-url';

interface AgentChatMarkdownProps {
  content: string;
}

export function AgentChatMarkdown({ content }: AgentChatMarkdownProps) {
  return (
    <div className="agent-md prose-ide prose-sm max-w-none text-left">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          // Model output must not cause an automatic browser request. Preserve
          // the image's text alternative without emitting img/srcset/preloads.
          img: ({ alt }) => alt ? <span>{alt}</span> : null,
          // Sohbet balonunda makale sarmalayıcısını gereksiz kenar boşlukları bırakma
          p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="my-1.5 list-disc pl-5 first:mt-0 last:mb-0">{children}</ul>,
          ol: ({ children }) => <ol className="my-1.5 list-decimal pl-5 first:mt-0 last:mb-0">{children}</ol>,
          li: ({ children }) => <li className="my-0.5">{children}</li>,
          h1: ({ children }) => <h3 className="mt-3 mb-1.5 font-mono text-sm font-semibold text-white first:mt-0">{children}</h3>,
          h2: ({ children }) => <h3 className="mt-3 mb-1.5 font-mono text-sm font-semibold text-white first:mt-0">{children}</h3>,
          h3: ({ children }) => <h4 className="mt-2.5 mb-1 font-mono text-xs font-semibold text-white first:mt-0">{children}</h4>,
          h4: ({ children }) => <h5 className="mt-2.5 mb-1 font-mono text-xs font-semibold text-white first:mt-0">{children}</h5>,
          h5: ({ children }) => <h6 className="mt-2 mb-1 font-mono text-xs font-semibold text-gray-200 first:mt-0">{children}</h6>,
          h6: ({ children }) => <h6 className="mt-2 mb-1 font-mono text-xs font-semibold text-gray-200 first:mt-0">{children}</h6>,
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-ide-border bg-black/40 px-2 py-1 text-left font-medium text-gray-200">{children}</th>
          ),
          td: ({ children }) => <td className="border border-ide-border px-2 py-1 text-gray-300">{children}</td>,
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
