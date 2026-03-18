'use client';

import { usePathname } from 'next/navigation';
import { FileText, Terminal } from 'lucide-react';

function getTabLabel(pathname: string): string {
  if (pathname === '/') return 'how-to-center.md';
  if (pathname === '/posts') return 'posts-list.md';
  if (pathname.startsWith('/posts/')) {
    const slug = pathname.replace('/posts/', '').split('/')[0];
    return `${slug}.md`;
  }
  return 'index.md';
}

interface IdeTabBarProps {
  isTerminalOpen?: boolean;
  onTerminalToggle?: () => void;
}

export function IdeTabBar({ isTerminalOpen = false, onTerminalToggle }: IdeTabBarProps) {
  const pathname = usePathname();
  const activeLabel = getTabLabel(pathname);

  return (
    <div className="flex bg-ide-sidebar h-9 border-b border-ide-border items-center shrink-0">
      {/* Active content tab */}
      <div className="bg-ide-bg border-r border-ide-border h-full px-4 flex items-center text-xs text-gray-300 gap-2 border-t-2 border-t-ide-primary font-mono">
        <FileText className="w-3.5 h-3.5 text-ide-primary shrink-0" />
        <span className="max-w-[240px] truncate">{activeLabel}</span>
      </div>

      {/* Terminal tab — toggles the terminal panel */}
      <button
        onClick={onTerminalToggle}
        className={`px-4 flex items-center text-xs gap-2 transition-all border-r border-ide-border h-full font-mono ${
          isTerminalOpen
            ? 'bg-ide-bg text-ide-primary border-t-2 border-t-ide-primary'
            : 'text-gray-500 opacity-60 hover:opacity-100 hover:text-gray-300'
        }`}
      >
        <Terminal className="w-3.5 h-3.5 shrink-0" />
        <span>terminal.sh</span>
      </button>
    </div>
  );
}
