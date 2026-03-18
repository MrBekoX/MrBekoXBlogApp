'use client';

import { useEffect, useRef } from 'react';
import { useAuthStore } from '@/stores/auth-store';
import { AUTH_CHANNEL_NAME, AUTH_STATE_EVENT, type AuthSyncMessage } from '@/lib/auth-events';

export function AuthSyncProvider({ children }: { children: React.ReactNode }) {
  const channelRef = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    try {
      channelRef.current = new BroadcastChannel(AUTH_CHANNEL_NAME);
      channelRef.current.onmessage = (event: MessageEvent<AuthSyncMessage>) => {
        if (event.data.type === 'logout') {
          useAuthStore.setState({ user: null, authStatus: 'unauthenticated', error: null, isLoading: false });
        } else if (event.data.type === 'login') {
          useAuthStore.setState({ user: event.data.user, authStatus: 'authenticated', error: null, isLoading: false });
        }
      };
    } catch {
      channelRef.current = null;
    }

    const handleAuthState = (event: Event) => {
      const customEvent = event as CustomEvent<AuthSyncMessage>;
      if (!customEvent.detail) {
        return;
      }

      if (customEvent.detail.type === 'logout') {
        useAuthStore.setState({ user: null, authStatus: 'unauthenticated', error: null, isLoading: false });
      } else if (customEvent.detail.type === 'login') {
        useAuthStore.setState({ user: customEvent.detail.user, authStatus: 'authenticated', error: null, isLoading: false });
      }
    };

    window.addEventListener(AUTH_STATE_EVENT, handleAuthState);

    return () => {
      channelRef.current?.close();
      window.removeEventListener(AUTH_STATE_EVENT, handleAuthState);
    };
  }, []);

  return <>{children}</>;
}
