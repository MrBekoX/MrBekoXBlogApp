'use client';

import { useState } from 'react';
import { IdeTabBar } from './ide-tab-bar';
import { IdeTerminal } from './ide-terminal';

interface IdeEditorAreaProps {
  children: React.ReactNode;
}

export function IdeEditorArea({ children }: IdeEditorAreaProps) {
  const [isTerminalOpen, setIsTerminalOpen] = useState(false);

  return (
    <main className="flex-1 bg-ide-bg flex flex-col min-w-0 overflow-hidden">
      <IdeTabBar
        isTerminalOpen={isTerminalOpen}
        onTerminalToggle={() => setIsTerminalOpen((prev) => !prev)}
      />

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto ide-scrollbar p-6 md:p-10 min-h-0">
        {children}
      </div>

      {/* Terminal panel — slides in at bottom */}
      {isTerminalOpen && (
        <IdeTerminal onClose={() => setIsTerminalOpen(false)} />
      )}
    </main>
  );
}
