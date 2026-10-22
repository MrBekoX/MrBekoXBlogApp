'use client';

/**
 * /about Who am I paneli: makalesiz, konu sabit 'who_am_i'.
 *
 * - İstek articleId/selectedText taşımaz; "Derin araştırma" (/agent/research) yok.
 * - Depolama: agent-run:v2:profile:{profileId}:who_am_i (makale anahtarlarından
 *   ayrı; sahte makale kimliği kullanılmaz). Geri yüklemede run'ın konusu
 *   backend'den doğrulanır (who_am_i olmayan run yüklenmez).
 * - Profil sürümü değişmiş eski sonuç backend sunum guard'ınca maskelenir;
 *   panel yerelleştirilmiş "güncellendi/kullanılamıyor" mesajı + yeniden sor sunar.
 */

import { useMemo } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { agentTexts } from '@/lib/agent-i18n';
import { profileRunStorageKey } from '@/lib/agent/storage';
import type { RestoreScope } from '@/lib/agent/session-model';
import { useAgentLang } from '@/hooks/use-agent-lang';
import { AgentChatPanel } from './agent-chat-panel';

interface ProfileAgentPanelProps {
  /** Backend'in döndürdüğü aktif profil kimliği (depolama anahtarı kapsamı). */
  profileId: string;
}

export function ProfileAgentPanel({ profileId }: ProfileAgentPanelProps) {
  const lang = useAgentLang();
  const t = agentTexts[lang];
  const storageKey = profileRunStorageKey(profileId);
  const restoreScope = useMemo<RestoreScope>(() => ({ topic: 'who_am_i' }), []);

  return (
    <Card className="border-ide-border bg-black/20" data-testid="profile-agent-panel" data-topic="who_am_i">
      <CardHeader>
        <CardTitle className="text-lg text-white">{t.whoAmIAskTitle}</CardTitle>
        <CardDescription>{t.whoAmIPanelDescription}</CardDescription>
        <div>
          <Badge variant="outline" className="text-[10px] text-gray-400">
            {t.topicLabel}: {t.topicWhoAmI}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <AgentChatPanel
          key={profileId}
          lang={lang}
          topic="who_am_i"
          storageKey={storageKey}
          restoreScope={restoreScope}
        />
      </CardContent>
    </Card>
  );
}
