import type { User } from '@/types';

export const AUTH_CHANNEL_NAME = 'auth-sync';
export type AuthSyncMessage =
  | { type: 'logout' }
  | { type: 'login'; user: User };

// Unique per-tab ID to filter out same-tab BroadcastChannel echoes.
// Same-tab state is already handled by Zustand set() — broadcast is only for cross-tab sync.
export const TAB_ID = typeof crypto !== 'undefined'
  ? crypto.randomUUID()
  : Math.random().toString(36).slice(2);

export function broadcastAuthMessage(message: AuthSyncMessage): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    const channel = new BroadcastChannel(AUTH_CHANNEL_NAME);
    channel.postMessage({ ...message, _tabId: TAB_ID });
    channel.close();
  } catch {
    // BroadcastChannel is optional in unsupported environments.
  }
}
