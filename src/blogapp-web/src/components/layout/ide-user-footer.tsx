'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/auth-store';
import { LayoutDashboard, LogOut } from 'lucide-react';

export function IdeUserFooter() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const authStatus = useAuthStore((s) => s.authStatus);
  const logout = useAuthStore((s) => s.logout);

  const isAuthenticated = authStatus === 'authenticated' && !!user;
  const isAdminOrAbove = user?.role && ['Author', 'Editor', 'Admin'].includes(user.role);

  const handleLogout = async () => {
    await logout();
    router.push('/');
    router.refresh();
  };

  return (
    <div className="p-3 border-t border-ide-border/50 shrink-0">
      <div className="flex items-center gap-3">
        {/* Avatar */}
        <img
          src="/images/avatar.jpg"
          alt="MrBekoX"
          className="w-8 h-8 rounded border border-gray-700 grayscale object-cover shrink-0"
          style={{ imageRendering: 'pixelated' }}
        />

        {/* Info + actions */}
        <div className="flex-1 min-w-0 text-[10px] font-mono">
          <p className="text-white font-bold leading-none mb-0.5 truncate">
            {isAuthenticated ? (user.fullName || user.userName) : 'MrBekoX'}
          </p>

          {isAuthenticated ? (
            /* Authenticated: role badge + action links */
            <>
              <p className="text-ide-primary mb-1.5 leading-none">{user.role}</p>
              <div className="flex items-center gap-2">
                {isAdminOrAbove && (
                  <Link
                    href="/mrbekox-console/dashboard"
                    className="flex items-center gap-1 text-gray-500 hover:text-ide-primary transition-colors"
                    title="Admin Dashboard"
                  >
                    <LayoutDashboard className="w-3 h-3" />
                    <span>dashboard</span>
                  </Link>
                )}
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-1 text-gray-500 hover:text-red-400 transition-colors"
                  title="Çıkış Yap"
                >
                  <LogOut className="w-3 h-3" />
                  <span>logout</span>
                </button>
              </div>
            </>
          ) : (
            /* Not authenticated: online status */
            <p className="text-green-500 leading-none">● Online</p>
          )}
        </div>
      </div>
    </div>
  );
}
