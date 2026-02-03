"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkUnwrapImages from "remark-unwrap-images"; 
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Copy, Check } from "lucide-react";

/**
 * XSS Protection: Validates URL to prevent javascript: and data: URIs
 * Only allows http:, https:, and relative paths
 */
function sanitizeUrl(url: string | undefined): string | undefined {
  if (!url) return undefined;
  
  // Decode URL to catch encoded attacks
  const decodedUrl = decodeURIComponent(url).trim().toLowerCase();
  
  // Block dangerous protocols
  const dangerousProtocols = ['javascript:', 'data:', 'vbscript:', 'file:'];
  for (const protocol of dangerousProtocols) {
    if (decodedUrl.startsWith(protocol)) {
      return undefined;
    }
  }
  
  // Allow http, https, and relative paths
  if (url.startsWith('http://') || url.startsWith('https://') || url.startsWith('/') || url.startsWith('#') || url.startsWith('./') || url.startsWith('../')) {
    return url;
  }
  
  // For other relative URLs (e.g., "image.png"), allow them
  if (!url.includes(':')) {
    return url;
  }
  
  return undefined;
}

interface MarkdownRendererProps {
  content: string;
  className?: string;
  title?: string;
  author?: string;
  date?: string;
  readingTime?: number;
  proseSize?: 'xs' | 'sm' | 'base' | 'lg' | 'xl';
  forChat?: boolean;  // New prop for chat messages
}

export function MarkdownRenderer({
  content,
  className = "",
  title,
  author = "MrBekoX",
  date,
  readingTime,
  proseSize = 'lg',
  forChat = false,
}: MarkdownRendererProps) {
  const [copiedCode, setCopiedCode] = React.useState<string | null>(null);

  // Map proseSize to Tailwind classes
  const proseClasses = {
    xs: 'prose-xs',
    sm: 'prose-sm',
    base: 'prose-base',
    lg: 'prose-lg',
    xl: 'prose-xl',
  };

  // For chat: Override prose size to text-sm regardless of proseSize prop
  const effectiveProseSize = forChat ? 'sm' : proseSize;

  const handleCopyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  return (
    <article
      className={`w-full max-w-3xl mx-auto px-4 sm:px-6 py-12 ${className}`}
    >
      {/* --- Header / Meta Alanı --- */}
      <header className="mb-10 text-center sm:text-left">
        {title && (
          <h1 className="text-4xl sm:text-5xl font-bold mb-6 font-serif leading-tight tracking-tight text-gray-900 dark:text-gray-100">
            {title}
          </h1>
        )}

        {(author || date || readingTime) && (
          <div className="flex flex-wrap items-center gap-4 text-sm text-gray-500 dark:text-gray-400 font-sans border-b border-gray-200 dark:border-gray-800 pb-8">
            {author && (
              <div className="flex items-center font-medium text-gray-900 dark:text-gray-200">
                <span>{author}</span>
              </div>
            )}
            {date && (
              <>
                <span className="hidden sm:inline">•</span>
                <span>
                  {new Date(date).toLocaleDateString("tr-TR", {
                    day: "numeric",
                    month: "long",
                    year: "numeric",
                  })}
                </span>
              </>
            )}
            {readingTime && (
              <>
                <span className="hidden sm:inline">•</span>
                <span>{readingTime} dk okuma</span>
              </>
            )}
          </div>
        )}
      </header>

      {/* --- İçerik Alanı --- */}
      <div className={`prose dark:prose-invert max-w-none prose-headings:font-serif prose-p:font-serif prose-a:text-blue-600 ${proseClasses[effectiveProseSize]} ${forChat ? '!text-sm !leading-relaxed prose-headings:!text-lg prose-h1:!text-xl prose-h2:!text-lg prose-h3:!text-base' : ''}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkUnwrapImages]} // ✅ Eklendi: remarkUnwrapImages
          components={{
            // Syntax Highlighting + Copy Button Entegrasyonu
            code: (props) => {
              const { inline, className, children } = props as {
                inline?: boolean;
                className?: string;
                children?: React.ReactNode;
              };
              const match = /language-(\w+)/.exec(className || "");
              const codeString = String(children).replace(/\n$/, "");

              if (!inline && match) {
                return (
                  <div className="relative group my-8 rounded-lg overflow-hidden shadow-2xl border border-gray-700/50">
                    {/* Dil Etiketi */}
                    <div className="absolute top-0 left-0 bg-gray-800 text-gray-400 text-xs px-3 py-1 rounded-br-lg z-10 border-b border-r border-gray-700">
                      {match[1].toUpperCase()}
                    </div>

                    {/* Kopyalama Butonu */}
                    <button
                      onClick={() => handleCopyCode(codeString)}
                      className="absolute top-2 right-2 p-2 bg-gray-700/50 hover:bg-gray-600 text-gray-300 rounded-md opacity-0 group-hover:opacity-100 transition-all duration-200 z-20 backdrop-blur-sm"
                      title="Kodu Kopyala"
                    >
                      {copiedCode === codeString ? (
                        <Check size={16} className="text-green-400" />
                      ) : (
                        <Copy size={16} />
                      )}
                    </button>

                    <SyntaxHighlighter
                      style={vscDarkPlus}
                      language={match[1]}
                      PreTag="div"
                      showLineNumbers={true}
                      wrapLines={true}
                      customStyle={{
                        margin: 0,
                        padding: "2.5rem 1rem 1rem 1rem",
                        backgroundColor: "#1e1e1e",
                        fontSize: forChat ? "0.8rem" : "0.9rem",  // Chat için daha küçük
                        lineHeight: "1.5",
                      }}
                    >
                      {codeString}
                    </SyntaxHighlighter>
                  </div>
                );
              }

              return (
                <code className={`px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 rounded font-mono text-orange-600 dark:text-orange-400 border border-gray-200 dark:border-gray-700 font-semibold ${forChat ? 'text-xs' : 'text-sm'}`}>
                  {children}
                </code>
              );
            },
            blockquote: ({ children }) => (
              <blockquote className="border-l-4 border-gray-900 dark:border-gray-100 pl-6 italic my-8 text-xl font-serif text-gray-700 dark:text-gray-300 bg-transparent">
                {children}
              </blockquote>
            ),
            img: ({ src, alt }) => {
              // XSS Protection: Sanitize image URL
              const safeSrc = sanitizeUrl(src);
              if (!safeSrc) return null;
              
              return (
                <figure className="my-10">
                  <img
                    src={safeSrc}
                    alt={alt || ''}
                    className="w-full rounded-lg shadow-md"
                    loading="lazy"
                  />
                  {alt && (
                    <figcaption className="text-center text-sm text-gray-500 mt-3 font-sans">
                      {alt}
                    </figcaption>
                  )}
                </figure>
              );
            },
            // XSS Protection: Sanitize link URLs
            a: ({ href, children, ...props }) => {
              const safeHref = sanitizeUrl(href);
              if (!safeHref) {
                return <span {...props}>{children}</span>;
              }
              return (
                <a 
                  href={safeHref} 
                  {...props}
                  rel="noopener noreferrer"
                  target={safeHref.startsWith('http') ? '_blank' : undefined}
                >
                  {children}
                </a>
              );
            },
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </article>
  );
}
