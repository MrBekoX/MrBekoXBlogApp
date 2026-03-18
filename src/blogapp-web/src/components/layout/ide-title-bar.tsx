'use client';

import { PanelLeftClose, PanelRightClose, PanelLeft, PanelRight } from 'lucide-react';
import { useSidebar } from './ide-sidebar-context';

export function IdeTitleBar() {
  const { leftSidebarOpen, rightSidebarOpen, toggleLeftSidebar, toggleRightSidebar } = useSidebar();

  return (
    <header className="h-10 bg-ide-sidebar border-b border-ide-border flex items-center justify-between px-4 shrink-0">
      {/* Left: mobile sidebar toggle + traffic lights + window title */}
      <div className="flex items-center space-x-2">
        {/* Mobile left sidebar toggle */}
        <button
          onClick={toggleLeftSidebar}
          className="lg:hidden p-1.5 hover:bg-white/10 rounded transition-colors"
          aria-label={leftSidebarOpen ? 'Close left sidebar' : 'Open left sidebar'}
        >
          {leftSidebarOpen ? (
            <PanelLeftClose className="w-4 h-4 text-gray-400" />
          ) : (
            <PanelLeft className="w-4 h-4 text-gray-400" />
          )}
        </button>

        <div className="flex space-x-1.5 mr-4">
          <div className="w-3 h-3 rounded-full bg-red-500/80" />
          <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
          <div className="w-3 h-3 rounded-full bg-green-500/80" />
        </div>
        <div className="text-xs flex items-center gap-2 opacity-70 text-gray-400 font-mono">
          <span className="text-[10px]">⌨</span>
          <span>mrbekox — dev-blog</span>
        </div>
      </div>

      {/* Right: IDE version + mobile right sidebar toggle */}
      <div className="flex items-center gap-2">
        <div className="text-xs font-medium tracking-wider text-gray-500 font-mono hidden sm:block">
          MRBEKOX IDE v2.0.4
        </div>

        {/* Mobile right sidebar toggle */}
        <button
          onClick={toggleRightSidebar}
          className="lg:hidden p-1.5 hover:bg-white/10 rounded transition-colors"
          aria-label={rightSidebarOpen ? 'Close right sidebar' : 'Open right sidebar'}
        >
          {rightSidebarOpen ? (
            <PanelRightClose className="w-4 h-4 text-gray-400" />
          ) : (
            <PanelRight className="w-4 h-4 text-gray-400" />
          )}
        </button>
      </div>
    </header>
  );
}
