import type { User } from '@/types';

export const AUTH_CHANNEL_NAME = 'auth-sync';
export const AUTH_STATE_EVENT = 'blogapp-auth-state';

export type AuthSyncMessage =
  | { type: 'logout' }
  | { type: 'login'; user: User };

export function broadcastAuthMessage(message: AuthSyncMessage): void {
  if (typeof window === 'undefined') {
    return;
  }

  window.dispatchEvent(new CustomEvent<AuthSyncMessage>(AUTH_STATE_EVENT, { detail: message }));

  try {
    const channel = new BroadcastChannel(AUTH_CHANNEL_NAME);
    channel.postMessage(message);
    channel.close();
  } catch {
    // BroadcastChannel is optional in unsupported environments.
  }
}
