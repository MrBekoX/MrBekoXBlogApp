'use client';

import { useEffect, ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { useSidebar } from './ide-sidebar-context';
import { X } from 'lucide-react';

interface MobileSidebarLeftProps {
  children: ReactNode;
}

export function MobileSidebarLeft({ children }: MobileSidebarLeftProps) {
  const { leftSidebarOpen, closeLeftSidebar } = useSidebar();
  const pathname = usePathname();

  // Close on route change
  useEffect(() => {
    if (leftSidebarOpen) {
      closeLeftSidebar();
    }
  }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  // Close on escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && leftSidebarOpen) {
        closeLeftSidebar();
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [leftSidebarOpen, closeLeftSidebar]);

  // Prevent body scroll when open
  useEffect(() => {
    if (leftSidebarOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [leftSidebarOpen]);

  return (
    <>
      {/* Desktop: render sidebar directly using display:contents */}
      <div className="hidden lg:contents">
        {children}
      </div>

      {/* Mobile: drawer overlay */}
      {leftSidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-50">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={closeLeftSidebar}
          />

          {/* Drawer */}
          <div
            className="absolute left-0 top-0 h-full w-72 bg-ide-sidebar shadow-2xl"
            style={{ animation: 'slideInLeft 0.3s ease-out' }}
          >
            {/* Close button */}
            <button
              onClick={closeLeftSidebar}
              className="absolute top-3 right-3 p-1.5 hover:bg-white/10 rounded transition-colors z-10"
              aria-label="Close sidebar"
            >
              <X className="w-4 h-4 text-gray-400" />
            </button>

            {/* Sidebar content */}
            <div className="h-full overflow-hidden flex flex-col">
              {children}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
