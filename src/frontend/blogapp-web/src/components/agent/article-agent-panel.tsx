'use client';

/**
 * Makale agent paneli — ortak AgentChatPanel'in makale bağlamı veren ince sarmalayıcısı.
 *
 * Props ve yerleşim değişmedi (posts/[slug]/page.tsx aynen kullanır). Ek olarak:
 * - "Konu" seçici (Otomatik / Who am I · Sample Author) "Çalışma tercihi"
 *   seçicisinden AYRIDIR. Konu değişimi yeni sohbet bağlamıdır: sohbet alt ağacı
 *   konu başına yeniden kurulur (yeni conversationId, ayrı depolama anahtarı);
 *   seçici bu alt ağacın DIŞINDA olduğundan klavye odağı korunur. Çalışma
 *   sürerken konu değiştirilemez.
 * - who_am_i'de makale bağlamı kutusu ve "Derin araştırma" düğmesi gösterilmez;
 *   istek articleId/selectedText taşımaz.
 * - Depolama: agent-run:v2:article:{articleId}:{topic}; eski agent-run:{articleId}
 *   kaydı bir kez auto anahtarına taşınır. Geri yüklemede run'ın konusu ve
 *   makalesi backend GET'ten doğrulanır.
 */

import { useCallback, useId, useMemo, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { agentTexts, agentTopicTexts } from '@/lib/agent-i18n';
import { normalizeTopic } from '@/lib/agent/topic';
import {
  articleRunStorageKey,
  migrateLegacyArticleRun,
  type StorageLike,
} from '@/lib/agent/storage';
import type { RestoreScope } from '@/lib/agent/session-model';
import { useAgentLang } from '@/hooks/use-agent-lang';
import type { AgentConversationTopic } from '@/types/agent';
import { AgentChatPanel } from './agent-chat-panel';

interface ArticleAgentPanelProps {
  /** Panelin bağlandığı makale (AÇIK bağlam tercihi için). */
  articleId: string;
  articleSlug: string;
}

export function ArticleAgentPanel({ articleId, articleSlug }: ArticleAgentPanelProps) {
  const lang = useAgentLang();
  const t = agentTexts[lang];
  const topicSelectId = useId();
  const topicHintId = useId();

  const [topic, setTopic] = useState<AgentConversationTopic>('auto');
  const [runActive, setRunActive] = useState(false);
  const [topicNotice, setTopicNotice] = useState('');

  const topicTexts = agentTopicTexts(lang, topic);
  const storageKey = articleRunStorageKey(articleId, topic);
  const restoreScope = useMemo<RestoreScope>(() => ({ topic, articleId }), [topic, articleId]);
  const article = useMemo(() => ({ articleId, articleSlug }), [articleId, articleSlug]);
  const prepareStorage = useCallback(
    (storage: StorageLike) => {
      migrateLegacyArticleRun(storage, articleId);
    },
    [articleId],
  );

  const changeTopic = (value: string) => {
    const next = normalizeTopic(value);
    if (runActive || next === topic) return;
    setRunActive(false);
    setTopic(next);
    setTopicNotice(t.topicChanged);
  };

  return (
    <Card className="border-ide-border bg-black/20" data-testid="agent-panel" data-topic={topic}>
      <CardHeader>
        <CardTitle className="text-lg text-white">{topicTexts.title}</CardTitle>
        <CardDescription>{topicTexts.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Konu seçimi: kaynak kapsamı (çalışma derinliğinden ayrı kavram) */}
        <div className="space-y-1">
          <Label htmlFor={topicSelectId} className="text-xs text-gray-400">
            {t.topicLabel}
          </Label>
          <select
            id={topicSelectId}
            value={topic}
            onChange={(event) => changeTopic(event.target.value)}
            disabled={runActive}
            aria-describedby={topicHintId}
            className="w-full rounded border border-ide-border bg-black/30 px-2 py-2 text-sm text-gray-200 disabled:cursor-not-allowed disabled:opacity-60 sm:max-w-sm"
          >
            <option value="auto">{t.topicAuto}</option>
            <option value="who_am_i">{t.topicWhoAmI}</option>
          </select>
          <p id={topicHintId} className="text-[10px] text-gray-600">
            {runActive ? t.topicLockedHint : t.topicHint}
          </p>
          <div aria-live="polite" role="status" className="sr-only">
            {topicNotice}
          </div>
        </div>

        <AgentChatPanel
          key={`${articleId}:${topic}`}
          lang={lang}
          topic={topic}
          storageKey={storageKey}
          restoreScope={restoreScope}
          article={article}
          prepareStorage={prepareStorage}
          onRunActiveChange={setRunActive}
        />
      </CardContent>
    </Card>
  );
}
