'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { X, Minus } from 'lucide-react';
import { API_BASE_URL } from '@/lib/env.client';

/* ─── Output line types ─────────────────────────────────────── */
type LineKind = 'cmd' | 'out' | 'err' | 'blank';

interface OutLine {
  id: number;
  kind: LineKind;
  text: string;
  color?: string;         // tailwind text-* class
  href?: string;          // makes the line a clickable link
}

let _id = 0;
const line = (kind: LineKind, text: string, color?: string, href?: string): OutLine =>
  ({ id: _id++, kind, text, color, href });

/* ─── Static command outputs ─────────────────────────────────── */
const HELP_LINES: OutLine[] = [
  line('out', 'Kullanılabilir komutlar:', 'text-ide-primary'),
  line('blank', ''),
  line('out', '  help          → bu listeyi göster'),
  line('out', '  whoami        → geliştirici hakkında'),
  line('out', '  skills        → teknoloji stack'),
  line('out', '  contact       → sosyal linkler'),
  line('out', '  ls            → yazı listesi (API\'den çekilir)'),
  line('out', '  ls posts/     → ↑ aynı'),
  line('out', '  cat <slug>    → yazıya git (ör: cat vim-shortcuts)'),
  line('out', '  stats         → blog istatistikleri'),
  line('out', '  clear         → terminali temizle'),
  line('out', '  exit          → terminali kapat'),
  line('blank', ''),
];

const WHOAMI_LINES: OutLine[] = [
  line('out', 'Berkay Kaplan', 'text-white'),
  line('out', 'Backend Developer & AI Enthusiast'),
  line('blank', ''),
  line('out', '  role      →  Software Developer'),
  line('out', '  location  →  Türkiye'),
  line('out', '  focus     →  .NET · Python · AI Agents · Microservices'),
  line('blank', ''),
];

const SKILLS_LINES: OutLine[] = [
  line('out', 'Tech Stack', 'text-ide-primary'),
  line('blank', ''),
  line('out', '  Programlama Dilleri', 'text-white'),
  line('out', '    →  C# · TypeScript · Python · JavaScript'),
  line('blank', ''),
  line('out', '  .NET Ekosistemi', 'text-white'),
  line('out', '    →  ASP.NET Core · Entity Framework Core · MediatR'),
  line('out', '    →  SignalR · Fluent Validation · Auto Mapper'),
  line('blank', ''),
  line('out', '  Frontend Teknolojileri', 'text-white'),
  line('out', '    →  Next.js · React · React Native'),
  line('blank', ''),
  line('out', '  Veritabanları & Önbellekleme', 'text-white'),
  line('out', '    →  PostgreSQL · SQL Server · SQLite · Redis'),
  line('blank', ''),
  line('out', '  Mimari', 'text-white'),
  line('out', '    →  Clean Architecture · N-Tier Architecture'),
  line('blank', ''),
  line('out', '  Bulut & DevOps', 'text-white'),
  line('out', '    →  Docker · Docker Compose · AWS EC2 · Linux · Git'),
  line('blank', ''),
  line('out', '  API & Güvenlik', 'text-white'),
  line('out', '    →  RESTful API · JWT Auth · RBAC · CORS · Rate Limiting'),
  line('blank', ''),
  line('out', '  Gözlemlenebilirlik', 'text-white'),
  line('out', '    →  Serilog · OpenTelemetry'),
  line('blank', ''),
  line('out', '  AI & LLM Entegrasyonu', 'text-white'),
  line('out', '    →  RAG · MCP · LangChain'),
  line('blank', ''),
];

const CONTACT_LINES: OutLine[] = [
  line('out', 'Sosyal Linkler', 'text-ide-primary'),
  line('blank', ''),
  line('out', '  GitHub    →  github.com/MrBekoX', 'text-blue-400', 'https://github.com/MrBekoX'),
  line('out', '  X         →  x.com/mrbeko_', 'text-blue-400', 'https://x.com/mrbeko_'),
  line('out', '  LinkedIn  →  linkedin.com/in/berkay-kaplan-133b35245', 'text-blue-400', 'https://www.linkedin.com/in/berkay-kaplan-133b35245/'),
  line('blank', ''),
];

/* ─── Welcome banner ─────────────────────────────────────────── */
const WELCOME: OutLine[] = [
  line('out', 'MrBekoX IDE v2.0.4 — terminal.sh', 'text-green-500'),
  line('out', "Type 'help' for available commands.", 'text-gray-600'),
  line('blank', ''),
];

/* ─── Component ──────────────────────────────────────────────── */
interface IdeTerminalProps {
  onClose: () => void;
}

export function IdeTerminal({ onClose }: IdeTerminalProps) {
  const router = useRouter();
  const [output, setOutput] = useState<OutLine[]>(WELCOME);
  const [input, setInput] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [isFetching, setIsFetching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  /* Auto-scroll to bottom */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [output]);

  /* Focus input on mount */
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const append = useCallback((lines: OutLine[]) => {
    setOutput((prev) => [...prev, ...lines]);
  }, []);

  /* ── Fetch posts from API ─── */
  const fetchPosts = useCallback(async () => {
    setIsFetching(true);
    append([line('out', 'yazılar yükleniyor...', 'text-gray-600')]);
    try {
      const res = await fetch(
        `${API_BASE_URL}/posts?status=Published&pageSize=20&sortBy=publishedat&sortDescending=true`
      );
      if (!res.ok) throw new Error('API hatası');
      const json = await res.json();
      const posts: Array<{ title: string; slug: string; publishedAt?: string; createdAt: string }> =
        json?.data?.items ?? [];

      if (!posts.length) {
        append([line('out', 'henüz yayınlanmış yazı yok.', 'text-gray-500')]);
        return;
      }

      const header: OutLine[] = [
        line('out', `${posts.length} yazı bulundu:`, 'text-ide-primary'),
        line('blank', ''),
      ];
      const rows: OutLine[] = posts.map((p) => {
        const date = p.publishedAt || p.createdAt;
        const d = date ? new Date(date).toLocaleDateString('tr-TR') : '';
        return line(
          'out',
          `  📄  ${p.slug}.md${' '.repeat(Math.max(1, 40 - p.slug.length))}${d}`,
          'text-gray-300',
          `/posts/${p.slug}`
        );
      });
      append([...header, ...rows, line('blank', '')]);
    } catch {
      append([line('err', 'yazılar alınamadı — API bağlantısını kontrol edin.')]);
    } finally {
      setIsFetching(false);
    }
  }, [append]);

  /* ── Fetch stats ─── */
  const fetchStats = useCallback(async () => {
    setIsFetching(true);
    append([line('out', 'istatistikler alınıyor...', 'text-gray-600')]);
    try {
      const res = await fetch(`${API_BASE_URL}/posts?status=Published&pageSize=1`);
      if (!res.ok) throw new Error();
      const json = await res.json();
      const total: number = json?.data?.totalCount ?? 0;
      const totalViews: number = json?.data?.items?.[0]?.viewCount ?? '—';

      append([
        line('out', 'Blog İstatistikleri', 'text-ide-primary'),
        line('blank', ''),
        line('out', `  total_posts   →  ${total}`),
        line('out', `  status        →  ● ONLINE`, 'text-green-500'),
        line('out', `  domain        →  mrbekox.dev`),
        line('blank', ''),
      ]);
    } catch {
      append([line('err', 'istatistikler alınamadı.')]);
    } finally {
      setIsFetching(false);
    }
  }, [append]);

  /* ── Command executor ─── */
  const execute = useCallback(
    (raw: string) => {
      const cmd = raw.trim().toLowerCase();
      const cmdLine = line('cmd', `$ ${raw.trim()}`);

      if (!cmd) return;

      // Add to history
      setHistory((h) => [raw.trim(), ...h.slice(0, 49)]);
      setHistoryIdx(-1);

      // Echo the command
      append([cmdLine]);

      switch (true) {
        case cmd === 'help':
          append(HELP_LINES);
          break;

        case cmd === 'whoami':
          append(WHOAMI_LINES);
          break;

        case cmd === 'skills':
          append(SKILLS_LINES);
          break;

        case cmd === 'contact':
          append(CONTACT_LINES);
          break;

        case cmd === 'ls' || cmd === 'ls posts/' || cmd === 'ls ./posts/':
          fetchPosts();
          break;

        case cmd === 'stats':
          fetchStats();
          break;

        case cmd.startsWith('cat '):
          {
            const slug = cmd.replace('cat ', '').replace('.md', '').trim();
            if (!slug) {
              append([line('err', 'kullanım: cat <slug>')]);
            } else {
              append([line('out', `→ /posts/${slug} sayfasına gidiliyor...`, 'text-ide-primary')]);
              setTimeout(() => router.push(`/posts/${slug}`), 400);
            }
          }
          break;

        case cmd === 'clear':
          setOutput([]);
          break;

        case cmd === 'exit':
          onClose();
          break;

        default:
          append([
            line('err', `komut bulunamadı: ${raw.trim()}`),
            line('out', "  'help' yazarak komut listesine bakabilirsiniz.", 'text-gray-600'),
            line('blank', ''),
          ]);
      }
    },
    [append, fetchPosts, fetchStats, router, onClose]
  );

  /* ── Keyboard handler ─── */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      execute(input);
      setInput('');
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const next = Math.min(historyIdx + 1, history.length - 1);
      setHistoryIdx(next);
      setInput(history[next] ?? '');
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = Math.max(historyIdx - 1, -1);
      setHistoryIdx(next);
      setInput(next === -1 ? '' : history[next] ?? '');
    }
  };

  return (
    <div className="h-52 flex flex-col border-t border-ide-border bg-ide-bg shrink-0 font-mono text-xs">
      {/* Panel header */}
      <div className="h-7 bg-ide-sidebar border-b border-ide-border flex items-center justify-between px-3 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-gray-500 uppercase tracking-widest">Terminal</span>
          <span className="text-[10px] bg-ide-bg border border-ide-border/60 px-2 py-0.5 rounded text-ide-primary">
            terminal.sh
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setOutput([])}
            title="Temizle"
            className="p-1 text-gray-600 hover:text-gray-400 transition-colors"
          >
            <Minus className="w-3 h-3" />
          </button>
          <button
            onClick={onClose}
            title="Kapat"
            className="p-1 text-gray-600 hover:text-red-400 transition-colors"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Output area */}
      <div
        className="flex-1 overflow-y-auto ide-scrollbar px-3 py-2 space-y-0.5 cursor-text"
        onClick={() => inputRef.current?.focus()}
      >
        {output.map((l) => {
          if (l.kind === 'blank') return <div key={l.id} className="h-2" />;

          const base =
            l.kind === 'cmd'
              ? 'text-ide-primary'
              : l.kind === 'err'
              ? 'text-red-400'
              : l.color ?? 'text-gray-400';

          if (l.href) {
            return (
              <div key={l.id}>
                <a
                  href={l.href}
                  target={l.href.startsWith('http') ? '_blank' : undefined}
                  rel="noopener noreferrer"
                  className={`${base} hover:underline hover:text-white cursor-pointer block whitespace-pre`}
                  onClick={(e) => {
                    if (!l.href!.startsWith('http')) {
                      e.preventDefault();
                      router.push(l.href!);
                    }
                  }}
                >
                  {l.text}
                </a>
              </div>
            );
          }

          return (
            <div key={l.id} className={`${base} whitespace-pre leading-relaxed`}>
              {l.text}
            </div>
          );
        })}

        {/* Active input line */}
        <div className="flex items-center gap-1.5 pt-0.5">
          <span className="text-ide-primary shrink-0">$</span>
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isFetching}
            placeholder={isFetching ? 'bekleniyor...' : ''}
            className="flex-1 bg-transparent text-white outline-none placeholder:text-gray-700 caret-ide-primary"
            autoComplete="off"
            spellCheck={false}
          />
        </div>

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
