import Link from 'next/link';
import { fetchTags } from '@/lib/server-api';
import { Github, Linkedin } from 'lucide-react';

// X (Twitter) Logo SVG
function XIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

const TAG_COLORS = [
  'bg-blue-500/10 text-blue-400 border-blue-500/20',
  'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  'bg-green-500/10 text-green-400 border-green-500/20',
  'bg-purple-500/10 text-purple-400 border-purple-500/20',
  'bg-red-500/10 text-red-400 border-red-500/20',
  'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  'bg-orange-500/10 text-orange-400 border-orange-500/20',
  'bg-pink-500/10 text-pink-400 border-pink-500/20',
];

export async function IdeSidebarRight() {
  const tags = await fetchTags();
  const visibleTags = (tags || []).slice(0, 12);

  return (
    <aside className="w-72 bg-ide-sidebar border-l border-ide-border flex flex-col shrink-0 h-full">
      {/* Inspector header */}
      <div className="p-3 uppercase text-[10px] font-bold tracking-widest text-gray-500 border-b border-ide-border/50 font-mono">
        Inspector &amp; Info
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto ide-scrollbar p-4 space-y-6">
        {/* System Stats */}
        <div className="space-y-3">
          <div className="text-[10px] text-gray-500 font-bold uppercase flex items-center justify-between font-mono">
            <span>System Stats</span>
            <span className="text-green-500">Stable</span>
          </div>
          <div className="bg-black/20 rounded p-3 border border-ide-border space-y-2 font-mono">
            <div className="flex justify-between text-xs">
              <span className="opacity-60">CPU Usage</span>
              <span className="text-ide-primary">14%</span>
            </div>
            <div className="w-full bg-gray-900 h-1.5 rounded-full overflow-hidden">
              <div className="bg-ide-primary h-full w-[14%]" />
            </div>
            <div className="flex justify-between text-xs mt-2">
              <span className="opacity-60">Uptime</span>
              <span className="text-gray-300">142:31:04</span>
            </div>
          </div>
        </div>

        {/* Quick Actions */}
        <div className="space-y-3">
          <div className="text-[10px] text-gray-500 font-bold uppercase font-mono">
            Quick Actions
          </div>
          <div className="grid grid-cols-1 gap-2">
            <a
              href="https://github.com/MrBekoX"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 p-2 rounded bg-white/5 hover:bg-white/10 text-xs transition-colors border border-ide-border/50 text-gray-400 hover:text-white font-mono"
            >
              <Github className="w-4 h-4 text-gray-500 shrink-0" />
              Github Repos
            </a>
            <a
              href="https://x.com/mrbeko_"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 p-2 rounded bg-white/5 hover:bg-white/10 text-xs transition-colors border border-ide-border/50 text-gray-400 hover:text-white font-mono"
            >
              <XIcon className="w-4 h-4 text-gray-500 shrink-0" />
              X Profile
            </a>
            <a
              href="https://www.linkedin.com/in/berkay-kaplan-133b35245/"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 p-2 rounded bg-white/5 hover:bg-white/10 text-xs transition-colors border border-ide-border/50 text-gray-400 hover:text-white font-mono"
            >
              <Linkedin className="w-4 h-4 text-gray-500 shrink-0" />
              LinkedIn Pro
            </a>
          </div>
        </div>

        {/* Active Tags */}
        {visibleTags.length > 0 && (
          <div className="space-y-3">
            <div className="text-[10px] text-gray-500 font-bold uppercase font-mono">
              Active Tags
            </div>
            <div className="flex flex-wrap gap-1.5">
              {visibleTags.map((tag, i) => (
                <Link
                  key={tag.id}
                  href={`/posts?tagId=${tag.id}`}
                  className={`px-2 py-0.5 border text-[10px] rounded font-mono transition-opacity hover:opacity-80 ${
                    TAG_COLORS[i % TAG_COLORS.length]
                  }`}
                >
                  {tag.name}
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>

    </aside>
  );
}
