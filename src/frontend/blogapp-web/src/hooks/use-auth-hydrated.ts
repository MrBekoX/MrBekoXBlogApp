import { useSyncExternalStore } from 'react';
import { useAuthStore } from '@/stores/auth-store';

function subscribe(onChange: () => void) {
  const unsubscribeStart = useAuthStore.persist.onHydrate(onChange);
  const unsubscribeFinish = useAuthStore.persist.onFinishHydration(onChange);
  return () => {
    unsubscribeStart();
    unsubscribeFinish();
  };
}

const getSnapshot = () => useAuthStore.persist.hasHydrated();
const getServerSnapshot = () => false;

/** Delay auth-dependent rendering until the persisted client store is ready. */
export function useAuthHydrated() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
