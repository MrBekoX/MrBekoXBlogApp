'use client';

import { useEffect, ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { useSidebar } from './ide-sidebar-context';
import { X } from 'lucide-react';

interface MobileSidebarRightProps {
  children: ReactNode;
}

export function MobileSidebarRight({ children }: MobileSidebarRightProps) {
  const { rightSidebarOpen, closeRightSidebar } = useSidebar();
  const pathname = usePathname();

  // Close on route change
  useEffect(() => {
    if (rightSidebarOpen) {
      closeRightSidebar();
    }
  }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  // Close on escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && rightSidebarOpen) {
        closeRightSidebar();
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [rightSidebarOpen, closeRightSidebar]);

  // Prevent body scroll when open
  useEffect(() => {
    if (rightSidebarOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [rightSidebarOpen]);

  return (
    <>
      {/* Desktop: render sidebar directly using display:contents */}
      <div className="hidden lg:contents">
        {children}
      </div>

      {/* Mobile: drawer overlay */}
      {rightSidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-50">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={closeRightSidebar}
          />

          {/* Drawer */}
          <div
            className="absolute right-0 top-0 h-full w-72 bg-ide-sidebar shadow-2xl"
            style={{ animation: 'slideInRight 0.3s ease-out' }}
          >
            {/* Close button */}
            <button
              onClick={closeRightSidebar}
              className="absolute top-3 left-3 p-1.5 hover:bg-white/10 rounded transition-colors z-10"
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
