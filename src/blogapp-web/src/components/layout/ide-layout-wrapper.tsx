'use client';

import { ReactNode } from 'react';
import { SidebarProvider } from './ide-sidebar-context';
import { MobileSidebarLeft } from './ide-mobile-sidebar-left';
import { MobileSidebarRight } from './ide-mobile-sidebar-right';
import { IdeTitleBar } from './ide-title-bar';
import { IdeStatusBar } from './ide-status-bar';
import { IdeEditorArea } from './ide-editor-area';

interface IdeLayoutWrapperProps {
  leftSidebar: ReactNode;
  rightSidebar: ReactNode;
  children: ReactNode;
}

export function IdeLayoutWrapper({ leftSidebar, rightSidebar, children }: IdeLayoutWrapperProps) {
  return (
    <SidebarProvider>
      <div className="flex flex-col h-screen overflow-hidden border border-ide-border bg-ide-bg text-gray-400 font-mono selection:bg-ide-primary selection:text-black">
        {/* CRT scanlines overlay */}
        <div className="scanlines" aria-hidden="true" />

        {/* Title bar */}
        <IdeTitleBar />

        {/* Main 3-column layout */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left sidebar — file explorer */}
          <MobileSidebarLeft>
            {leftSidebar}
          </MobileSidebarLeft>

          {/* Editor area — manages tab bar + content + terminal panel */}
          <IdeEditorArea>{children}</IdeEditorArea>

          {/* Right sidebar — inspector */}
          <MobileSidebarRight>
            {rightSidebar}
          </MobileSidebarRight>
        </div>

        {/* Status bar */}
        <IdeStatusBar />
      </div>
    </SidebarProvider>
  );
}
