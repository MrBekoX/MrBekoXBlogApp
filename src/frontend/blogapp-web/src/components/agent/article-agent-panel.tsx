'use client';

/**
 * Makale agent paneli (B10). Plan UI listesi:
 * - Makaleye soru sorma + AÇIK makale bağlamı tercihi.
 * - Auto/fast/analysis/deep research tercihi (deep research ayrı uç nokta).
 * - Kabul / başlama / tamamlanma durumlarının AYRI gösterimi.
 * - Kaynak kartları + bölüm bağlantıları.
 * - İlerleme, iptal ve SAYFA YENİLEME SONRASI GERİ DÖNÜŞ (GET replay).
 * - Türkçe/İngilizce metinler + aria-live erişilebilir durum bildirimi.
 * Canlı ilerleme: SignalR (AgentRunsHub "RunUpdated"); bağlantı yoksa GET replay
 * yoklamasıyla devam eder. Sahiplik backend'dedir; run_id yalnız bu oturumun
 * localStorage'ında tutulur (başka oturumda GET 403 döner ve panel sessiz kalır).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { HubConnection, HubConnectionBuilder, LogLevel } from '@microsoft/signalr';
import { Loader2, Send, Square, ExternalLink, BookOpen, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { MarkdownRenderer } from '@/components/markdown-renderer';
import { agentApi, agentErrorMessage } from '@/lib/agent-api';
import { agentTexts, detectAgentLang, type AgentLang } from '@/lib/agent-i18n';
import { AGENT_RUNS_HUB_URL } from '@/lib/env';
import type {
  AgentModePreference,
  AgentPhase,
  AgentRunCitation,
  AgentRunStatus,
} from '@/types/agent';

const RUN_STORAGE_PREFIX = 'agent-run:';

interface ArticleAgentPanelProps {
  /** Panelin bağlandığı makale (AÇIK bağlam tercihi için). */
  articleId: string;
  articleSlug: string;
}

export function ArticleAgentPanel({ articleId, articleSlug }: ArticleAgentPanelProps) {
  const [lang] = useState<AgentLang>(() => detectAgentLang());
  const t = agentTexts[lang];

  const [question, setQuestion] = useState('');
  const [modePreference, setModePreference] = useState<AgentModePreference>('auto');
  const [includeArticleContext, setIncludeArticleContext] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const [runId, setRunId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [run, setRun] = useState<AgentRunStatus | null>(null);
  const [phase, setPhase] = useState<AgentPhase>('idle');
  const [announcement, setAnnouncement] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [liveConnected, setLiveConnected] = useState(false);

  const connectionRef = useRef<HubConnection | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const announce = useCallback((message: string) => {
    setAnnouncement(message);
  }, []);

  /** Terminal durumları faz makinesine çevirir. */
  const phaseFromStatus = useCallback(
    (status: AgentRunStatus): AgentPhase => {
      switch (status.status) {
        case 'Completed':
          return 'completed';
        case 'PartiallyCompleted':
          return 'partial';
        case 'Failed':
          return 'failed';
        case 'Cancelled':
          return 'cancelled';
        default:
          // Accepted: mod seçilmediyse başlama bekleniyor; seçildiyse başladı.
          return status.selectedMode ? 'started' : 'starting';
      }
    },
    [],
  );

  /** GET replay: durum + commit edilmiş projection olayları (yenileme sonrası geri dönüş). */
  const refreshRun = useCallback(
    async (id: string) => {
      try {
        const status = await agentApi.getRun(id);
        setRun(status);
        setPhase(phaseFromStatus(status));
        announce(`${t.a11yStatusPrefix}: ${statusText(status, phaseFromStatus(status), t)}`);
        return status;
      } catch {
        return null;
      }
    },
    [announce, phaseFromStatus, t],
  );

  // Sayfa yenileme sonrası geri dönüş: bu makale için kayıtlı run varsa replay.
  useEffect(() => {
    const stored = window.localStorage.getItem(RUN_STORAGE_PREFIX + articleId);
    if (!stored) return;
    setRunId(stored);
    refreshRun(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [articleId]);

  // Terminal olmayan run için: SignalR canlı bildirim + GET replay yedek yoklaması.
  useEffect(() => {
    if (!runId || !run) return;
    const terminal = ['Completed', 'PartiallyCompleted', 'Failed', 'Cancelled'].includes(run.status);
    if (terminal) return;

    let disposed = false;

    // 1) Canlı kanal: AgentRunsHub (B5) — sahipliği backend doğrulayan grup üyeliği.
    // withCredentials: misafir çerezi negotiate'e taşınır (sahiplik kaynağı backend).
    const connection = new HubConnectionBuilder()
      .withUrl(AGENT_RUNS_HUB_URL, { withCredentials: true })
      .configureLogging(LogLevel.Warning)
      .withAutomaticReconnect()
      .build();
    connectionRef.current = connection;

    connection.on('RunUpdated', (payload: { run_id?: string; status?: string; result?: unknown }) => {
      if (disposed || payload.run_id !== runId) return;
      // Bildirim durum değişiminde projection'ın commit edilmiş kaydından taze oku:
      // replay kaynağı HER ZAMAN commit edilmiş projection'dır (plan kuralı).
      void refreshRun(runId);
    });

    connection
      .start()
      .then(() => connection.invoke('SubscribeToRun', runId))
      .then(() => {
        if (!disposed) setLiveConnected(true);
      })
      .catch(() => {
        // Canlı kanal yok: replay yoklaması tek başına yeterli (alternatif/eşdeğer).
        if (!disposed) setLiveConnected(false);
      });

    // 2) Yedek: 4 sn'de bir GET replay (kopukluk penceresini tamamlar).
    const poll = () => {
      if (disposed) return;
      void refreshRun(runId).then(() => {
        pollTimerRef.current = setTimeout(poll, 4000);
      });
    };
    pollTimerRef.current = setTimeout(poll, 4000);

    return () => {
      disposed = true;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      connection.stop().catch(() => undefined);
      connectionRef.current = null;
      setLiveConnected(false);
    };
  }, [runId, run?.status, refreshRun, t]);

  const submit = useCallback(
    async (deepResearch: boolean) => {
      const trimmed = question.trim();
      if (!trimmed || submitting) return;

      setSubmitting(true);
      setError(null);
      setPhase('submitting');
      announce(t.statusSubmitting);

      const idempotencyKey =
        typeof crypto !== 'undefined' && 'randomUUID' in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

      const payload = {
        question: trimmed,
        language: lang,
        budgetProfile: 'standard',
        articleId: includeArticleContext ? articleId : undefined,
        conversationId,
        idempotencyKey,
      };

      try {
        const accepted = deepResearch
          ? await agentApi.startResearch(payload)
          : await agentApi.sendMessage({ ...payload, modePreference });

        setRunId(accepted.runId);
        setConversationId(accepted.conversationId);
        window.localStorage.setItem(RUN_STORAGE_PREFIX + articleId, accepted.runId);
        setPhase('accepted');
        announce(t.statusAccepted);

        // Kabul hemen projection'a düşmüş olabilir; ilk replay'i çek.
        await refreshRun(accepted.runId);
      } catch (err) {
        setPhase('idle');
        setError(agentErrorMessage(err, t.errorGeneric));
        announce(t.errorGeneric);
      } finally {
        setSubmitting(false);
      }
    },
    [announce, articleId, conversationId, includeArticleContext, lang, modePreference, question, refreshRun, submitting, t],
  );

  const cancel = useCallback(async () => {
    if (!runId) return;
    if (!window.confirm(t.cancelConfirm)) return;
    try {
      await agentApi.cancelRun(runId);
      // "requested" TERMINAL DEĞİLDİR (B7): iptal isteniyor gösterilir; terminal
      // cancelled olayı projection replay'iyle gelir.
      setPhase('cancelling');
      announce(t.statusCancelling);
    } catch (err) {
      setError(agentErrorMessage(err, t.errorGeneric));
    }
  }, [announce, runId, t]);

  const reset = useCallback(() => {
    window.localStorage.removeItem(RUN_STORAGE_PREFIX + articleId);
    setRunId(null);
    setRun(null);
    setPhase('idle');
    setQuestion('');
  }, [articleId]);

  const busy = phase === 'submitting';
  const terminalPhases: AgentPhase[] = ['completed', 'partial', 'failed', 'cancelled'];
  const isTerminal = terminalPhases.includes(phase);

  return (
    <Card className="border-ide-border bg-black/20" data-testid="agent-panel">
      <CardHeader>
        <CardTitle className="text-lg text-white">{t.panelTitle}</CardTitle>
        <CardDescription>{t.panelDescription}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Erişilebilir durum bildirimi (aria-live) */}
        <div aria-live="polite" role="status" className="sr-only">
          {announcement}
        </div>

        {!runId && (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              void submit(false);
            }}
          >
            <div className="space-y-1">
              <Label htmlFor="agent-question" className="text-xs text-gray-400">
                {t.questionLabel}
              </Label>
              <Textarea
                id="agent-question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder={t.questionPlaceholder}
                rows={3}
                maxLength={8000}
                className="bg-black/30 border-ide-border text-sm text-gray-200"
              />
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <div className="space-y-1 flex-1">
                <Label htmlFor="agent-mode" className="text-xs text-gray-400">
                  {t.modeLabel}
                </Label>
                <select
                  id="agent-mode"
                  value={modePreference}
                  onChange={(event) => setModePreference(event.target.value as AgentModePreference)}
                  className="w-full rounded border border-ide-border bg-black/30 px-2 py-2 text-sm text-gray-200"
                >
                  <option value="auto">{t.modeAuto}</option>
                  <option value="fast">{t.modeFast}</option>
                  <option value="analysis">{t.modeAnalysis}</option>
                  <option value="deep_research">{t.modeDeepResearch}</option>
                </select>
              </div>
            </div>

            <label className="flex items-center gap-2 text-xs text-gray-400">
              <input
                type="checkbox"
                checked={includeArticleContext}
                onChange={(event) => setIncludeArticleContext(event.target.checked)}
                className="accent-ide-primary"
              />
              {t.includeArticleContext}
            </label>

            {error && (
              <p role="alert" className="text-xs text-red-400">
                {error}
              </p>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                type="submit"
                disabled={busy || !question.trim()}
                className="gap-2"
                size="sm"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {busy ? t.sending : t.send}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy || !question.trim()}
                onClick={() => void submit(true)}
                className="gap-2"
              >
                {t.modeDeepResearch}
              </Button>
            </div>
          </form>
        )}

        {runId && run && (
          <div className="space-y-4" data-testid="agent-run" data-phase={phase}>
            {/* AYRIK durum şeridi: kabul → başlama → tamamlanma */}
            <ol className="flex flex-wrap items-center gap-2 text-xs" aria-label={t.a11yStatusPrefix}>
              <StatusStep done label={runId ? t.statusAccepted : ''} active={phase === 'accepted' || phase === 'submitting'} />
              <StatusStep
                done={['started', 'completed', 'partial', 'failed', 'cancelled', 'cancelling'].includes(phase)}
                label={phase === 'starting' ? t.statusStarting : t.statusStarted}
                active={phase === 'starting' || phase === 'started'}
              />
              <StatusStep
                done={isTerminal}
                label={terminalLabel(phase, t)}
                active={phase === 'cancelling'}
              />
            </ol>

            <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
              {phase === 'starting' && <Badge variant="outline">{t.statusStarting}</Badge>}
              {phase === 'started' && (
                <Badge variant="outline" className="gap-1">
                  <Loader2 className="h-3 w-3 animate-spin" /> {t.statusStarted}
                  {run.selectedMode ? ` · ${run.selectedMode}` : ''}
                </Badge>
              )}
              {phase === 'cancelling' && <Badge variant="outline">{t.statusCancelling}</Badge>}
              <span className="text-gray-600">{liveConnected ? t.liveUpdatesOn : t.liveUpdatesOff}</span>
            </div>

            <p className="text-sm text-gray-300">
              <span className="text-gray-500">{t.askedQuestion}: </span>
              {run.question}
            </p>

            {/* Terminal sonuç: izin verilen sonuç (maskeleme gerekçesi dahil) */}
            {run.result && (
              <div className="space-y-3 rounded border border-ide-border bg-black/20 p-3">
                {run.result.unavailableReason ? (
                  <p className="text-sm text-amber-400">
                    {t.contentUnavailable}: {run.result.unavailableReason}
                  </p>
                ) : (
                  <>
                    {run.result.answer && (
                      <div>
                        <p className="mb-1 text-xs uppercase text-gray-500">{t.answerHeading}</p>
                        <MarkdownRenderer content={run.result.answer} author="" />
                      </div>
                    )}
                    {run.result.report && (
                      <div>
                        <p className="mb-1 text-xs uppercase text-gray-500">{t.reportHeading}</p>
                        <MarkdownRenderer content={run.result.report} author="" />
                      </div>
                    )}
                    {run.result.unresolvedQuestion && (
                      <p className="text-xs text-gray-400">{t.unresolved}: {run.result.unresolvedQuestion}</p>
                    )}
                    {run.result.citations.length > 0 && (
                      <div className="space-y-2">
                        <p className="text-xs uppercase text-gray-500">{t.sources}</p>
                        <ul className="space-y-1">
                          {run.result.citations.map((citation, index) => (
                            <li key={`${citation.sourceId ?? citation.url ?? index}-${index}`}>
                              <SourceCard citation={citation} articleSlug={articleSlug} lang={lang} />
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              {!isTerminal && phase !== 'cancelling' && (
                <Button variant="outline" size="sm" onClick={() => void cancel()} className="gap-2">
                  <Square className="h-3 w-3" /> {t.cancel}
                </Button>
              )}
              {isTerminal && (
                <Button variant="outline" size="sm" onClick={reset} className="gap-2">
                  <RotateCcw className="h-3 w-3" /> {t.retry}
                </Button>
              )}
            </div>

            {isTerminal && <FeedbackRow runId={runId} lang={lang} />}
          </div>
        )}

        {runId && !run && (
          <p className="flex items-center gap-2 text-xs text-gray-400">
            <Loader2 className="h-3 w-3 animate-spin" /> {t.statusAccepted}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function StatusStep({ done, active, label }: { done: boolean; active: boolean; label: string }) {
  if (!label) return null;
  return (
    <li
      className={`flex items-center gap-1 ${
        done ? 'text-emerald-400' : active ? 'text-gray-200' : 'text-gray-600'
      }`}
      aria-current={active ? 'step' : undefined}
    >
      <span className={`inline-block h-2 w-2 rounded-full ${done ? 'bg-emerald-400' : active ? 'bg-gray-200' : 'bg-gray-700'}`} />
      {label}
      <span className="text-gray-700">→</span>
    </li>
  );
}

function terminalLabel(phase: AgentPhase, t: (typeof agentTexts)['tr']): string {
  switch (phase) {
    case 'completed':
      return t.statusCompleted;
    case 'partial':
      return t.statusPartial;
    case 'failed':
      return t.statusFailed;
    case 'cancelled':
      return t.statusCancelled;
    default:
      return t.statusCancelling;
  }
}

function statusText(
  status: AgentRunStatus,
  phase: AgentPhase,
  t: (typeof agentTexts)['tr'],
): string {
  return terminalLabel(phase, t) === t.statusCancelling
    ? t.statusCancelling
    : `${status.status}`;
}

function SourceCard({
  citation,
  articleSlug,
  lang,
}: {
  citation: AgentRunCitation;
  articleSlug: string;
  lang: AgentLang;
}) {
  const t = agentTexts[lang];

  if (citation.kind === 'article') {
    // Bölüm bağlantısı: source_id "article:{id}#bolum" biçimindeyse anchor çıkar (A4 sözleşmesi).
    const section = citation.sourceId?.split('#')[1];
    const href = section ? `/posts/${articleSlug}#${section}` : `/posts/${articleSlug}`;
    return (
      <Link
        href={href}
        className="flex items-center gap-2 rounded border border-ide-border px-2 py-1 text-xs text-gray-300 hover:border-ide-primary hover:text-ide-primary"
      >
        <BookOpen className="h-3 w-3" />
        <span>{citation.title ?? t.sourceArticle}</span>
        {section && <span className="text-gray-600">#{section}</span>}
      </Link>
    );
  }

  return (
    <a
      href={citation.url ?? '#'}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="flex items-center gap-2 rounded border border-ide-border px-2 py-1 text-xs text-gray-300 hover:border-ide-primary hover:text-ide-primary"
    >
      <ExternalLink className="h-3 w-3" />
      <span>{citation.title ?? citation.url ?? t.sourceWeb}</span>
    </a>
  );
}

/** Terminal sonuç sonrası idempotent geri bildirim satırı (1-5 puan). */
function FeedbackRow({ runId, lang }: { runId: string; lang: AgentLang }) {
  const t = agentTexts[lang];
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setSent(window.localStorage.getItem(`agent-feedback:${runId}`) === '1');
  }, [runId]);

  const rate = async (rating: number) => {
    setBusy(true);
    try {
      const key =
        typeof crypto !== 'undefined' && 'randomUUID' in crypto
          ? crypto.randomUUID()
          : `${runId}-${rating}-${Date.now()}`;
      await agentApi.sendFeedback(runId, rating, key);
      window.localStorage.setItem(`agent-feedback:${runId}`, '1');
      setSent(true);
    } catch {
      // sessiz: geri bildirim kritik değil
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return <p className="text-xs text-gray-500">{t.feedbackThanks}</p>;
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
      <span>{t.feedbackQuestion}</span>
      {[1, 2, 3, 4, 5].map((rating) => (
        <button
          key={rating}
          type="button"
          disabled={busy}
          onClick={() => void rate(rating)}
          aria-label={`${t.feedbackQuestion} ${rating}/5`}
          className="rounded border border-ide-border px-2 py-0.5 hover:border-ide-primary hover:text-ide-primary"
        >
          {rating}
        </button>
      ))}
    </div>
  );
}
