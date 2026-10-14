'use client';

/**
 * Agent sohbet yanıtı markdown görünümü. Makale sayfasıyla AYNI zincir:
 * react-markdown + remark-gfm + rehype-highlight (package.json bağımlıları;
 * yeni paket eklenmedi). Raw HTML kaçırılır (rehype-raw YOK); react-markdown'ın
 * varsayılan URL transformu javascript:/data: şemalarını eler.
 * hljs-* token renkleri için küçük, bileşenle sınırlı koyu tema — site tasarım
 * diliyle (IDE paleti: amber primary, slate gri tonları) uyumlu; globals.css'e
 * dokunulmaz.
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';

/** Bileşen-sınırlı highlight.js token renkleri (koyu; One Dark ailesiyle uyumlu). */
const AGENT_HLJS_CSS = `
.agent-md pre code.hljs{display:block;background:transparent;padding:0;overflow-x:auto;color:#d4d4d4}
.agent-md .hljs-comment,.agent-md .hljs-quote{color:#6a737d;font-style:italic}
.agent-md .hljs-keyword,.agent-md .hljs-selector-tag,.agent-md .hljs-meta .hljs-keyword,.agent-md .hljs-doctag,.agent-md .hljs-template-tag{color:#c678dd}
.agent-md .hljs-string,.agent-md .hljs-regexp,.agent-md .hljs-addition,.agent-md .hljs-meta .hljs-string{color:#98c379}
.agent-md .hljs-number,.agent-md .hljs-literal,.agent-md .hljs-attr,.agent-md .hljs-attribute,.agent-md .hljs-variable,.agent-md .hljs-template-variable,.agent-md .hljs-param{color:#d19a66}
.agent-md .hljs-title,.agent-md .hljs-title.function_,.agent-md .hljs-section,.agent-md .hljs-name,.agent-md .hljs-selector-id,.agent-md .hljs-selector-class{color:#61afef}
.agent-md .hljs-type,.agent-md .hljs-built_in,.agent-md .hljs-builtin-name,.agent-md .hljs-class .hljs-title,.agent-md .hljs-title.class_{color:#e5c07b}
.agent-md .hljs-symbol,.agent-md .hljs-bullet,.agent-md .hljs-link{color:#56b6c2}
.agent-md .hljs-deletion{color:#e06c75}
.agent-md .hljs-emphasis{font-style:italic}.agent-md .hljs-strong{font-weight:600}
`;

interface AgentChatMarkdownProps {
  content: string;
}

export function AgentChatMarkdown({ content }: AgentChatMarkdownProps) {
  return (
    <div className="agent-md prose-ide prose-sm max-w-none text-left">
      <style>{AGENT_HLJS_CSS}</style>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
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
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
