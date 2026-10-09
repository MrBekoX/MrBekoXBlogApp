'use client';

import { useEffect, useRef } from 'react';
import { useAuthStore } from '@/stores/auth-store';
import { AUTH_CHANNEL_NAME, TAB_ID, type AuthSyncMessage } from '@/lib/auth-events';

export function AuthSyncProvider({ children }: { children: React.ReactNode }) {
  const channelRef = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    try {
      channelRef.current = new BroadcastChannel(AUTH_CHANNEL_NAME);
      channelRef.current.onmessage = (event: MessageEvent<AuthSyncMessage & { _tabId?: string }>) => {
        // Ignore echoes from the same tab — same-tab state is already
        // handled by Zustand set() in auth-store actions.
        if (event.data._tabId === TAB_ID) return;

        if (event.data.type === 'logout') {
          useAuthStore.setState({ user: null, authStatus: 'unauthenticated', error: null, isLoading: false });
        } else if (event.data.type === 'login') {
          useAuthStore.setState({ user: event.data.user, authStatus: 'authenticated', error: null, isLoading: false });
        }
      };
    } catch {
      channelRef.current = null;
    }

    return () => {
      channelRef.current?.close();
    };
  }, []);

  return <>{children}</>;
}
