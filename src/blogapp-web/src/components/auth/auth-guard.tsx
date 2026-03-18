'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/auth-store';
import type { User } from '@/types';

type AllowedRole = 'Admin' | 'Editor' | 'Author' | 'Reader';

interface AuthGuardProps {
  children: React.ReactNode;
  /** Minimum required roles to access. If not specified, any authenticated user can access. */
  allowedRoles?: AllowedRole[];
  /** URL to redirect to when not authenticated. Defaults to '/mrbekox-console' */
  loginUrl?: string;
  /** URL to redirect to when authenticated but not authorized. Defaults to '/' */
  unauthorizedUrl?: string;
  /** Custom loading component */
  loadingComponent?: React.ReactNode;
  /** Custom unauthorized component */
  unauthorizedComponent?: React.ReactNode;
}

/**
 * AuthGuard component that protects routes requiring authentication.
 *
 * Features:
 * - Uses persisted auth state from sessionStorage
 * - Handles hydration correctly (no flash of wrong content)
 * - Supports role-based access control
 * - Prevents redirect loops with circuit breaker pattern
 *
 * Usage:
 * ```tsx
 * <AuthGuard allowedRoles={['Admin', 'Editor']}>
 *   <DashboardContent />
 * </AuthGuard>
 * ```
 */
export function AuthGuard({
  children,
  allowedRoles,
  loginUrl = '/mrbekox-console',
  unauthorizedUrl = '/',
  loadingComponent,
  unauthorizedComponent,
}: AuthGuardProps) {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const authStatus = useAuthStore((state) => state.authStatus);
  const checkAuth = useAuthStore((state) => state.checkAuth);
  const [hasMounted, setHasMounted] = useState(false);
  const hasCheckedAuth = useRef(false);
  const hasRedirected = useRef(false);

  // Mark as mounted after hydration
  useEffect(() => {
    setHasMounted(true);
  }, []);

  // Check auth status only once per mount
  // Trust persisted state from sessionStorage
  useEffect(() => {
    if (!hasMounted || hasCheckedAuth.current) return;

    // If we have a persisted authenticated state, trust it
    if (authStatus === 'authenticated' && user) {
      hasCheckedAuth.current = true;
      return;
    }

    // If we have a persisted unauthenticated state, trust it
    if (authStatus === 'unauthenticated') {
      hasCheckedAuth.current = true;
      return;
    }

    // Only check auth if we're in 'idle' state (no persisted state)
    if (authStatus === 'idle') {
      hasCheckedAuth.current = true;
      checkAuth();
    }
  }, [hasMounted, authStatus, user, checkAuth]);

  // Handle redirects with circuit breaker
  useEffect(() => {
    if (!hasMounted) return;
    if (authStatus === 'idle' || authStatus === 'checking') return;
    if (hasRedirected.current) return;

    if (authStatus === 'unauthenticated') {
      hasRedirected.current = true;
      // Use setTimeout to prevent immediate redirect loop
      const timer = setTimeout(() => {
        router.replace(loginUrl);
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [hasMounted, authStatus, router, loginUrl]);

  // Show loading during SSR, hydration, or auth check
  if (!hasMounted || authStatus === 'idle' || authStatus === 'checking') {
    return loadingComponent ?? <DefaultLoadingComponent />;
  }

  // Not authenticated - show loading (redirect is happening)
  if (authStatus === 'unauthenticated') {
    return loadingComponent ?? <DefaultLoadingComponent />;
  }

  // Check role authorization
  if (allowedRoles && allowedRoles.length > 0) {
    const userRole = user?.role as AllowedRole | undefined;
    if (!userRole || !allowedRoles.includes(userRole)) {
      if (unauthorizedComponent) {
        return <>{unauthorizedComponent}</>;
      }
      return <DefaultUnauthorizedComponent redirectUrl={unauthorizedUrl} />;
    }
  }

  // Authenticated and authorized
  return <>{children}</>;
}

function DefaultLoadingComponent() {
  return (
    <div className="container flex min-h-[50vh] items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto" />
        <p className="mt-4 text-muted-foreground">Yetki kontrol ediliyor...</p>
      </div>
    </div>
  );
}

function DefaultUnauthorizedComponent({ redirectUrl }: { redirectUrl: string }) {
  const router = useRouter();

  return (
    <div className="container flex min-h-[50vh] items-center justify-center">
      <div className="text-center">
        <h1 className="text-2xl font-bold">Yetkisiz Erişim</h1>
        <p className="mt-2 text-muted-foreground">
          Bu sayfaya erişim yetkiniz bulunmuyor.
        </p>
        <button
          onClick={() => router.push(redirectUrl)}
          className="mt-4 inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Ana Sayfaya Dön
        </button>
      </div>
    </div>
  );
}

/**
 * Hook to check if current user has required role
 */
export function useHasRole(allowedRoles: AllowedRole[]): boolean {
  const user = useAuthStore((state) => state.user);
  const authStatus = useAuthStore((state) => state.authStatus);

  if (authStatus !== 'authenticated' || !user) {
    return false;
  }

  const userRole = user.role as AllowedRole | undefined;
  return userRole ? allowedRoles.includes(userRole) : false;
}

/**
 * Hook to get current auth state with proper typing
 */
export function useAuth() {
  const user = useAuthStore((state) => state.user);
  const authStatus = useAuthStore((state) => state.authStatus);
  const login = useAuthStore((state) => state.login);
  const logout = useAuthStore((state) => state.logout);
  const checkAuth = useAuthStore((state) => state.checkAuth);

  return {
    user,
    isAuthenticated: authStatus === 'authenticated',
    isLoading: authStatus === 'checking' || authStatus === 'idle',
    authStatus,
    login,
    logout,
    checkAuth,
  };
}
