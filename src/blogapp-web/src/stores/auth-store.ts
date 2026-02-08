import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User } from '@/types';
import { authApi, getErrorMessage } from '@/lib/api';

/**
 * Auth status represents the current authentication state.
 * - 'idle': Initial state, auth hasn't been checked yet
 * - 'checking': Currently verifying auth with backend
 * - 'authenticated': User is authenticated
 * - 'unauthenticated': User is not authenticated
 */
type AuthStatus = 'idle' | 'checking' | 'authenticated' | 'unauthenticated';

interface AuthState {
  user: User | null;
  authStatus: AuthStatus;
  isLoading: boolean;
  error: string | null;

  // Actions
  login: (email: string, password: string) => Promise<boolean>;
  register: (data: { userName: string; email: string; password: string; confirmPassword: string; firstName?: string; lastName?: string }) => Promise<boolean>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
  clearError: () => void;
  reset: () => void;
}

// Store for tracking in-flight auth check to prevent duplicates
let authCheckPromise: Promise<void> | null = null;

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      authStatus: 'idle',
      isLoading: false,
      error: null,

      login: async (email: string, password: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await authApi.login({ email, password });
          if (response.success && response.data) {
            set({
              user: response.data.user,
              authStatus: 'authenticated',
              isLoading: false,
            });
            return true;
          } else {
            set({ error: response.message || 'Login failed', isLoading: false });
            return false;
          }
        } catch (error) {
          const message = getErrorMessage(error, 'Giriş başarısız');
          set({ error: message, isLoading: false });
          return false;
        }
      },

      register: async (data) => {
        set({ isLoading: true, error: null });
        try {
          const response = await authApi.register(data);
          if (response.success && response.data) {
            set({
              user: response.data.user,
              authStatus: 'authenticated',
              isLoading: false,
            });
            return true;
          } else {
            set({ error: response.message || 'Kayıt başarısız', isLoading: false });
            return false;
          }
        } catch (error) {
          const message = getErrorMessage(error, 'Kayıt başarısız');
          set({ error: message, isLoading: false });
          return false;
        }
      },

      logout: async () => {
        try {
          await authApi.logout();
        } catch {
          // Ignore logout errors
        } finally {
          set({ user: null, authStatus: 'unauthenticated' });
        }
      },

      checkAuth: async () => {
        const state = get();

        // If already checking, wait for the existing check to complete
        if (authCheckPromise) {
          await authCheckPromise;
          // Re-check state after promise completes - another call may have set auth
          const newState = get();
          if (newState.authStatus !== 'unauthenticated') {
            return;
          }
          return;
        }

        // If already authenticated and we have a user, skip the check
        // (login/register already set the state correctly)
        if (state.authStatus === 'authenticated' && state.user) {
          return;
        }

        set({ authStatus: 'checking' });

        authCheckPromise = (async () => {
          try {
            const response = await authApi.getCurrentUser();
            if (response.success && response.data) {
              set({ user: response.data, authStatus: 'authenticated' });
            } else {
              set({ user: null, authStatus: 'unauthenticated' });
            }
          } catch (error) {
            if (error && typeof error === 'object' && 'response' in error) {
              const axiosError = error as { response?: { status?: number } };

              // 401 means not authenticated
              if (axiosError.response?.status === 401) {
                set({ user: null, authStatus: 'unauthenticated' });
                return;
              }

              // 429 rate limit - treat as unauthenticated to prevent infinite loop
              if (axiosError.response?.status === 429) {
                set({ user: null, authStatus: 'unauthenticated' });
                return;
              }
            }

            set({ user: null, authStatus: 'unauthenticated' });
          } finally {
            authCheckPromise = null;
          }
        })();

        await authCheckPromise;
      },

      clearError: () => set({ error: null }),

      reset: () => set({ user: null, authStatus: 'idle', error: null }),
    }),
    {
      name: 'auth-storage',
      // Persist both user and authStatus to prevent infinite loops
      // On page load, if unauthenticated, don't call checkAuth
      // If authenticated, verify with backend once
      partialize: (state) => ({
        user: state.user ? {
          id: state.user.id,
          userName: state.user.userName,
          fullName: state.user.fullName,
          role: state.user.role,
          avatarUrl: state.user.avatarUrl,
          // Exclude: email
        } as typeof state.user : null,
        authStatus: state.authStatus === 'checking' ? 'idle' : state.authStatus,
      }),
    }
  )
);
