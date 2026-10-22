'use client';

import { useSyncExternalStore } from 'react';
import { AGENT_SERVER_LANG, detectAgentLang, type AgentLang } from '@/lib/agent-i18n';

function subscribe(onChange: () => void): () => void {
  window.addEventListener('languagechange', onChange);
  return () => window.removeEventListener('languagechange', onChange);
}

function getServerSnapshot(): AgentLang {
  return AGENT_SERVER_LANG;
}

/**
 * Hydration-güvenli panel dili. Sunucu HTML'i ve ilk hydration render'ı sabit
 * 'tr' kullanır (getServerSnapshot); tarayıcı dili (navigator.language) mount
 * SONRASI uygulanır — EN tarayıcılarda useState(detectAgentLang) kaynaklı
 * hydration uyuşmazlığı oluşmaz.
 */
export function useAgentLang(): AgentLang {
  return useSyncExternalStore(subscribe, detectAgentLang, getServerSnapshot);
}
