import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { User } from '@/types';
import { authApi, getErrorMessage, invalidateCsrfToken } from '@/lib/api';
import { broadcastAuthMessage } from '@/lib/auth-events';

type AuthStatus = 'idle' | 'checking' | 'authenticated' | 'unauthenticated';

interface AuthState {
  user: User | null;
  authStatus: AuthStatus;
  isLoading: boolean;
  error: string | null;
  lastAuthCheck: number | null;
  login: (email: string, password: string, operationId?: string) => Promise<boolean>;
  register: (
    data: { userName: string; email: string; password: string; confirmPassword: string; firstName?: string; lastName?: string },
    operationId?: string,
  ) => Promise<boolean>;
  logout: (operationId?: string) => Promise<void>;
  checkAuth: (force?: boolean) => Promise<void>;
  clearError: () => void;
  reset: () => void;
}

let authCheckPromise: Promise<void> | null = null;

// Cooldown period for auth checks (5 seconds)
const AUTH_CHECK_COOLDOWN_MS = 5000;

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      authStatus: 'idle',
      isLoading: false,
      error: null,
      lastAuthCheck: null,

      login: async (email: string, password: string, operationId?: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await authApi.login({ email, password }, operationId);
          if (response.success && response.data) {
            invalidateCsrfToken();
            set({
              user: response.data.user,
              authStatus: 'authenticated',
              isLoading: false,
              lastAuthCheck: Date.now(),
            });
            broadcastAuthMessage({ type: 'login', user: response.data.user });
            return true;
          }

          set({ error: response.message || 'Giris basarisiz', isLoading: false });
          return false;
        } catch (error) {
          set({ error: getErrorMessage(error, 'Giris basarisiz'), isLoading: false });
          return false;
        }
      },

      register: async (data, operationId?: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await authApi.register(data, operationId);
          if (response.success && response.data) {
            invalidateCsrfToken();
            set({
              user: response.data.user,
              authStatus: 'authenticated',
              isLoading: false,
              lastAuthCheck: Date.now(),
            });
            broadcastAuthMessage({ type: 'login', user: response.data.user });
            return true;
          }

          set({ error: response.message || 'Kayit basarisiz', isLoading: false });
          return false;
        } catch (error) {
          set({ error: getErrorMessage(error, 'Kayit basarisiz'), isLoading: false });
          return false;
        }
      },

      logout: async (operationId?: string) => {
        try {
          await authApi.logout(operationId);
        } catch {
          // Ignore logout errors.
        } finally {
          invalidateCsrfToken();
          set({
            user: null,
            authStatus: 'unauthenticated',
            isLoading: false,
            error: null,
            lastAuthCheck: Date.now(),
          });
          broadcastAuthMessage({ type: 'logout' });
        }
      },

      checkAuth: async (force = false) => {
        const state = get();

        // If already checking, wait for that to complete
        if (authCheckPromise) {
          await authCheckPromise;
          return;
        }

        // If already authenticated and not forcing, skip
        if (!force && state.authStatus === 'authenticated' && state.user) {
          return;
        }

        // Check cooldown (unless forcing)
        if (!force && state.lastAuthCheck) {
          const timeSinceLastCheck = Date.now() - state.lastAuthCheck;
          if (timeSinceLastCheck < AUTH_CHECK_COOLDOWN_MS) {
            return;
          }
        }

        set({ authStatus: 'checking' });

        authCheckPromise = (async () => {
          try {
            const response = await authApi.getCurrentUser();
            if (response.success && response.data) {
              set({
                user: response.data,
                authStatus: 'authenticated',
                error: null,
                lastAuthCheck: Date.now(),
              });
              return;
            }
          } catch {
            // fall through to unauthenticated state
          } finally {
            authCheckPromise = null;
          }

          set({
            user: null,
            authStatus: 'unauthenticated',
            lastAuthCheck: Date.now(),
          });
        })();

        await authCheckPromise;
      },

      clearError: () => set({ error: null }),

      reset: () => set({
        user: null,
        authStatus: 'idle',
        error: null,
        isLoading: false,
        lastAuthCheck: null,
      }),
    }),
    {
      name: 'blogapp-auth',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        user: state.user,
        authStatus: state.authStatus,
        lastAuthCheck: state.lastAuthCheck,
      }),
      merge: (persistedState, currentState) => {
        const persisted = (persistedState ?? {}) as Partial<AuthState>;

        let authStatus = persisted.authStatus ?? currentState.authStatus;
        let user = persisted.user ?? currentState.user;

        // 'checking' durumu hydration'da hayatta kalmamali (browser crash vb.)
        if (authStatus === 'checking') {
          authStatus = 'idle';
        }

        // State tutarliligi: authenticated ama user yok → sifirla
        if (authStatus === 'authenticated' && !user) {
          authStatus = 'idle';
          user = null;
        }

        return {
          ...currentState,
          ...persisted,
          authStatus,
          user,
        };
      },
    }
  )
);
