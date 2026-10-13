'use client';

/**
 * Makale agent paneli — sohbet arayüzü + canlı işlem adımları.
 *
 * Plan UI listesi (B10 + canlı adım dalga):
 * - Sohbet: kullanıcı + agent mesaj balonları; agent yanıtı react-markdown +
 *   remark-gfm + rehype-highlight zinciriyle (listeler/kod blokları/linkler).
 * - Canlı işlem adımları: yalnız GERÇEK progressed/terminal olaylarından
 *   (commit edilmiş projection replay'i); sahte adım/sahte ilerleme YOK.
 *   Token-parça akışı altyapısı olmadığından yanıt terminal olayda TAM gelir —
 *   arayüz bunu dürüst gösterir: adımlar canlı akar, cevap tamamlanınca gelir.
 * - GERÇEK ZAMAN: SignalR AgentRunsHub ("RunUpdated" bildirimi; grup run:{runId},
 *   sahiplik backend'de). Bildirim TETİKLEYİCİDİR: adım verisi her zaman
 *   getEvents(after) commit edilmiş replay'inden okunur (B5 hub sözleşmesi).
 *   Kopan bağlantı getEvents(after) replay ile toparlanır; polling yalnız
 *   bağlantı hiç kurulamadığında SON ÇARE fallback'tir.
 * - eventSequence monoton filtresi: <= son gelen yok sayılır; duplicate/geç
 *   olay adım çoğaltamaz ve terminali geri çeviremez.
 * - Kontroller: Enter gönder / Shift+Enter satır; çalışırken DURDUR (gerçek
 *   POST cancel → "iptal isteniyor" → terminal cancelled beklenir); başarısız
 *   terminalde TEKRAR DENE (son soruyu yeniden gönderir); boş sohbet önerileri.
 * - Kaydırma: kullanıcı en alttayken otomatik takip; yukarı kaydırdıysa
 *   "Yeni içerik" pill'i; tıklayınca alta iner.
 * - Erişilebilirlik: aria-live="polite" durum bildirimi, adım accordion'ı
 *   button+aria-expanded, tam klavye kullanımı, prefers-reduced-motion,
 *   mobil tek kolon.
 * Sahiplik backend'dedir; run_id yalnız bu oturumun localStorage'ında tutulur
 * (başka oturumda GET 403 döner ve panel sessiz kalır). Sayfa yenileme sonrası
 * GET replay ile son çalışma geri yüklenir.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { HubConnection, HubConnectionBuilder, LogLevel } from '@microsoft/signalr';
import {
  ArrowDown,
  Bot,
  BookOpen,
  ExternalLink,
  Loader2,
  RotateCcw,
  Send,
  Square,
  User,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { agentApi, agentErrorMessage } from '@/lib/agent-api';
import { agentTexts, detectAgentLang, type AgentLang } from '@/lib/agent-i18n';
import { AGENT_RUNS_HUB_URL } from '@/lib/env';
import type {
  AgentModePreference,
  AgentPhase,
  AgentRunCitation,
  AgentRunEvent,
  AgentRunNotification,
  AgentRunStatus,
} from '@/types/agent';
import { AgentChatMarkdown } from './agent-chat-markdown';
import { AgentStepsPanel } from './agent-steps';
import {
  buildAgentSteps,
  deriveEventKind,
  isTerminalKind,
  type AgentStepVM,
} from './agent-steps-model';

const RUN_STORAGE_PREFIX = 'agent-run:';
/** Yoklama fallback aralığı (yalnız SignalR hiç kurulamadığında). */
const POLL_FALLBACK_MS = 4000;

const TERMINAL_PHASES: AgentPhase[] = ['completed', 'partial', 'failed', 'cancelled'];
const ACTIVE_PHASES: AgentPhase[] = ['accepted', 'starting', 'started', 'cancelling'];

type ChannelState = 'connecting' | 'live' | 'polling';

interface ArticleAgentPanelProps {
  /** Panelin bağlandığı makale (AÇIK bağlam tercihi için). */
  articleId: string;
  articleSlug: string;
}

/** Sohbetteki tek çalışma (soru + canlı durum + terminal sonuç). */
interface AgentTurn {
  runId: string;
  question: string;
  isResearch: boolean;
  phase: AgentPhase;
  status: AgentRunStatus | null;
}

export function ArticleAgentPanel({ articleId, articleSlug }: ArticleAgentPanelProps) {
  const [lang] = useState<AgentLang>(() => detectAgentLang());
  const t = agentTexts[lang];

  const [question, setQuestion] = useState('');
  const [modePreference, setModePreference] = useState<AgentModePreference>('auto');
  const [includeArticleContext, setIncludeArticleContext] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);

  const [turns, setTurns] = useState<AgentTurn[]>([]);
  const [steps, setSteps] = useState<AgentStepVM[]>([]);
  const [stepsOpen, setStepsOpen] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [channel, setChannel] = useState<ChannelState>('connecting');
  const [nowTick, setNowTick] = useState(() => Date.now());
  const [showNewContent, setShowNewContent] = useState(false);

  const connectionRef = useRef<HubConnection | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollStoppedRef = useRef(false);
  /** Commit edilmiş projection'dan okunan son event_sequence (monoton imlek). */
  const lastSequenceRef = useRef(0);
  const eventsRef = useRef<AgentRunEvent[]>([]);
  const ingestBusyRef = useRef(false);
  const ingestRerunRef = useRef(false);
  const terminalHandledRef = useRef(false);
  const startedSeenRef = useRef(false);
  const autoCollapseDoneRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const atBottomRef = useRef(true);
  const lastAnnouncementRef = useRef('');

  const activeTurn = turns.length > 0 ? turns[turns.length - 1] : null;
  const activeRunId = activeTurn?.runId ?? null;
  const activeIsTerminal = activeTurn ? TERMINAL_PHASES.includes(activeTurn.phase) : false;
  const isRunActive = submitting || (activeTurn ? ACTIVE_PHASES.includes(activeTurn.phase) : false);

  const announce = useCallback(
    (message: string) => {
      if (lastAnnouncementRef.current === message) return;
      lastAnnouncementRef.current = message;
      setAnnouncement(message);
    },
    [],
  );

  /** Terminal durumları faz makinesine çevirir. */
  const phaseFromStatus = useCallback((status: AgentRunStatus): AgentPhase => {
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
  }, []);

  const patchTurn = useCallback((runId: string, patch: Partial<AgentTurn>) => {
    setTurns((prev) => prev.map((turn) => (turn.runId === runId ? { ...turn, ...patch } : turn)));
  }, []);

  /** GET /runs/{runId}: durum + guard'dan geçmiş terminal sonuç (yetkili kaynak). */
  const refreshStatus = useCallback(
    async (runId: string): Promise<AgentRunStatus | null> => {
      try {
        const status = await agentApi.getRun(runId);
        const nextPhase = phaseFromStatus(status);
        patchTurn(runId, { status, phase: nextPhase });
        if (TERMINAL_PHASES.includes(nextPhase)) {
          announce(terminalLabel(nextPhase, t));
        } else if (nextPhase === 'started') {
          announce(t.statusStarted);
        }
        return status;
      } catch {
        return null; // 403/404: sessiz (başka oturum / kayıt yok)
      }
    },
    [announce, patchTurn, phaseFromStatus, t],
  );

  /** Yeni projection olaylarını monoton filtreyle al; adımları GERÇEK olaylardan kur. */
  const ingestEvents = useCallback(
    async (runId: string) => {
      if (ingestBusyRef.current) {
        ingestRerunRef.current = true;
        return;
      }
      ingestBusyRef.current = true;
      try {
        for (let pass = 0; pass < 3; pass += 1) {
          const rerunPending = ingestRerunRef.current;
          ingestRerunRef.current = false;

          const page = await agentApi.getEvents(runId, lastSequenceRef.current);
          // Monoton filtre: <= son gelen (duplicate/geç olay) yok sayılır.
          const fresh = page.events.filter((event) => event.eventSequence > lastSequenceRef.current);
          if (fresh.length > 0) {
            lastSequenceRef.current = fresh[fresh.length - 1].eventSequence;
            eventsRef.current = [...eventsRef.current, ...fresh];
            setSteps(buildAgentSteps(eventsRef.current));

            if (!startedSeenRef.current) {
              startedSeenRef.current = true;
              patchTurn(runId, { phase: 'started' });
              announce(t.statusStarted);
            }

            const sawTerminal = fresh.some((event) => {
              const kind = deriveEventKind(event);
              return kind !== null && isTerminalKind(kind);
            });
            if (sawTerminal && !terminalHandledRef.current) {
              terminalHandledRef.current = true;
              // Terminal sonucu guard'lı GET'ten tazele (push maskeli olabilir).
              await refreshStatus(runId);
            }
          }

          if (!page.hasMore && !rerunPending) break;
        }
      } catch {
        // Tek replay okuma hatası: sonraki bildirim/yoklama yeniden dener.
      } finally {
        ingestBusyRef.current = false;
      }
    },
    [announce, patchTurn, refreshStatus, t],
  );

  // Sayfa yenileme sonrası geri dönüş: bu makale için kayıtlı SON run'ı replay et.
  useEffect(() => {
    const stored = window.localStorage.getItem(RUN_STORAGE_PREFIX + articleId);
    if (!stored) return;
    setTurns([{ runId: stored, question: '', isResearch: false, phase: 'starting', status: null }]);
    void (async () => {
      const status = await refreshStatus(stored);
      // Çalışma sürerken adım alanı açık başlar; terminal kayıt kapalı gelir.
      if (!status || !TERMINAL_PHASES.includes(phaseFromStatus(status))) {
        setStepsOpen(true);
      }
      await ingestEvents(stored);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [articleId]);

  // GERÇEK ZAMAN: SignalR AgentRunsHub. Bildirim tetikleyicidir; veri replay'den.
  useEffect(() => {
    const runId = activeRunId;
    if (!runId || activeIsTerminal) return;

    let disposed = false;
    pollStoppedRef.current = false;

    const stopPollingFallback = () => {
      pollStoppedRef.current = true;
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };

    const startPollingFallback = () => {
      if (pollTimerRef.current || pollStoppedRef.current) return;
      setChannel('polling');
      const poll = () => {
        pollTimerRef.current = setTimeout(() => {
          void ingestEvents(runId).finally(() => {
            if (!pollStoppedRef.current) poll();
          });
        }, POLL_FALLBACK_MS);
      };
      poll();
    };

    // 1) Canlı kanal: AgentRunsHub (B5) — sahipliği backend doğrulayan grup üyeliği.
    const connection = new HubConnectionBuilder()
      .withUrl(AGENT_RUNS_HUB_URL, { withCredentials: true })
      .configureLogging(LogLevel.Warning)
      .withAutomaticReconnect()
      .build();
    connectionRef.current = connection;

    connection.on('RunUpdated', (payload: AgentRunNotification) => {
      if (disposed || payload.run_id !== runId) return;
      // duplicate/geç bildirim: replay imlecinden geriye kalmışsa yok say.
      if (typeof payload.event_sequence === 'number' && payload.event_sequence <= lastSequenceRef.current) {
        return;
      }
      void ingestEvents(runId);
    });

    connection.onreconnected(() => {
      if (disposed) return;
      // Kopukluk penceresini replay ile toparla; grup üyeliği reconnect sonrası yeniden gerekir.
      void connection.invoke('SubscribeToRun', runId).catch(() => undefined);
      void ingestEvents(runId);
      void refreshStatus(runId);
    });

    connection.onclose(() => {
      if (disposed) return;
      // Yeniden bağlanma denemeleri tükendi: SON ÇARE yoklama.
      stopPollingFallback();
      pollStoppedRef.current = false;
      startPollingFallback();
    });

    connection
      .start()
      .then(() => connection.invoke('SubscribeToRun', runId))
      .then(() => {
        if (!disposed) {
          setChannel('live');
          // Bağlantı gecikmişse aradaki olayları kaçırma.
          void ingestEvents(runId);
        }
      })
      .catch(() => {
        // Canlı kanal hiç kurulamadı: SON ÇARE replay yoklaması.
        if (!disposed) startPollingFallback();
      });

    return () => {
      disposed = true;
      stopPollingFallback();
      connection.stop().catch(() => undefined);
      if (connectionRef.current === connection) connectionRef.current = null;
      setChannel('connecting');
    };
  }, [activeRunId, activeIsTerminal, ingestEvents, refreshStatus]);

  // Çalışan adım için canlı elapsed saati (yalnız gerçekten çalışırken).
  const hasSteps = steps.length > 0;
  useEffect(() => {
    if (!isRunActive || !hasSteps) return;
    const timer = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [isRunActive, hasSteps]);

  // Terminalde adım alanı bir kez otomatik kapanır (kullanıcı açabilir).
  useEffect(() => {
    if (activeIsTerminal && !autoCollapseDoneRef.current) {
      autoCollapseDoneRef.current = true;
      setStepsOpen(false);
    }
  }, [activeIsTerminal]);

  // Takip: kullanıcı en alttaysa yeni içeriğe otomatik kaydır; değilse pill göster.
  const lastResult = activeTurn?.status?.result ?? null;
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (atBottomRef.current) {
      el.scrollTo({ top: el.scrollHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
    } else {
      setShowNewContent(true);
    }
  }, [steps.length, turns.length, lastResult]);

  const startRun = useCallback(
    (accepted: { runId: string; conversationId: string }, questionText: string, isResearch: boolean) => {
      // Yeni çalışma: replay imlecini sıfırla.
      lastSequenceRef.current = 0;
      eventsRef.current = [];
      terminalHandledRef.current = false;
      startedSeenRef.current = false;
      autoCollapseDoneRef.current = false;
      ingestRerunRef.current = false;
      setSteps([]);
      setStepsOpen(true);
      setConversationId(accepted.conversationId);
      window.localStorage.setItem(RUN_STORAGE_PREFIX + articleId, accepted.runId);
      setTurns((prev) => [
        ...prev,
        {
          runId: accepted.runId,
          question: questionText,
          isResearch,
          phase: 'accepted',
          status: null,
        },
      ]);
    },
    [articleId],
  );

  const submit = useCallback(
    async (questionText: string, deepResearch: boolean) => {
      const trimmed = questionText.trim();
      if (!trimmed || submitting || isRunActive) return;

      setSubmitting(true);
      setError(null);
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

        startRun(accepted, trimmed, deepResearch);
        announce(t.statusAccepted);
        setQuestion('');

        // Kabul hemen projection'a düşmüş olabilir; ilk replay'i çek.
        void refreshStatus(accepted.runId);
        void ingestEvents(accepted.runId);
      } catch (err) {
        setError(agentErrorMessage(err, t.errorGeneric));
        announce(t.errorGeneric);
      } finally {
        setSubmitting(false);
      }
    },
    [
      announce,
      articleId,
      conversationId,
      includeArticleContext,
      ingestEvents,
      isRunActive,
      lang,
      modePreference,
      refreshStatus,
      startRun,
      submitting,
      t,
    ],
  );

  const cancel = useCallback(async () => {
    const runId = activeRunId;
    if (!runId) return;
    if (!window.confirm(t.cancelConfirm)) return;
    try {
      await agentApi.cancelRun(runId);
      // "requested" TERMINAL DEĞİLDİR (B7): iptal isteniyor gösterilir; sahte
      // "iptal edildi" YAZILMAZ — terminal cancelled olayı replay'den gelir.
      patchTurn(runId, { phase: 'cancelling' });
      announce(t.cancelRequestedNote);
    } catch (err) {
      setError(agentErrorMessage(err, t.errorGeneric));
    }
  }, [activeRunId, announce, patchTurn, t]);

  /** Başarısız terminalde TEKRAR DENE: son soruyu yeniden gönderir. */
  const retryLast = useCallback(() => {
    if (!activeTurn || activeTurn.phase !== 'failed') return;
    const text = activeTurn.question || activeTurn.status?.question || '';
    if (!text.trim()) return;
    void submit(text, activeTurn.isResearch);
  }, [activeTurn, submit]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    atBottomRef.current = nearBottom;
    if (nearBottom) setShowNewContent(false);
  }, []);

  const jumpToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = true;
    setShowNewContent(false);
    el.scrollTo({ top: el.scrollHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  }, []);

  const canSubmit = question.trim().length > 0 && !submitting && !isRunActive;
  const suggestions = [t.suggestionSummary, t.suggestionMainIdea, t.suggestionCode];

  const handleSubmitQuestion = (text: string, deepResearch: boolean) => {
    if (text.trim().length === 0) return;
    void submit(text, deepResearch);
  };

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

        {/* Sohbet alanı */}
        <div className="relative">
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            role="log"
            aria-label={t.chatLabel}
            className="ide-scrollbar max-h-[560px] min-h-[140px] space-y-4 overflow-y-auto pr-1"
          >
            {turns.length === 0 && !submitting && (
              <div className="flex flex-col gap-2 py-2">
                <p className="text-xs text-gray-500">{t.panelDescription}</p>
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-gray-600">{t.suggestionsLabel}</span>
                  {suggestions.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => {
                        setQuestion(suggestion);
                        inputRef.current?.focus();
                      }}
                      className="min-h-[28px] rounded-full border border-ide-border px-2.5 py-1 text-xs text-gray-400 transition-colors hover:border-ide-primary hover:text-ide-primary"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {turns.map((turn, index) => {
              const isLatest = index === turns.length - 1;
              const runActive = isLatest && ACTIVE_PHASES.includes(turn.phase);
              return (
                <div
                  key={turn.runId}
                  data-testid={isLatest ? 'agent-run' : undefined}
                  data-phase={turn.phase}
                  className="space-y-2"
                >
                  <UserBubble text={turn.question || turn.status?.question || ''} label={t.youLabel} />
                  <AssistantBubble label={t.agentLabel}>
                    {isLatest ? (
                      <AgentStepsPanel
                        steps={steps}
                        runActive={runActive}
                        lang={lang}
                        open={stepsOpen}
                        onToggle={() => setStepsOpen((prev) => !prev)}
                        now={nowTick}
                      />
                    ) : null}

                    {runActive && steps.length === 0 && (
                      <p className="flex items-center gap-2 text-xs text-gray-400">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        {turn.phase === 'accepted' || turn.phase === 'starting'
                          ? t.statusAccepted
                          : t.statusStarted}
                      </p>
                    )}

                    {turn.phase === 'cancelling' && (
                      <p className="flex items-center gap-2 text-xs text-amber-400">
                        <Loader2 className="h-3 w-3 animate-spin" /> {t.statusCancelling}
                      </p>
                    )}

                    {/* Terminal sonuç: izin verilen sonuç (maskeleme gerekçesi dahil) */}
                    {turn.status?.result && TERMINAL_PHASES.includes(turn.phase) && (
                      <TurnResult turn={turn} articleSlug={articleSlug} lang={lang} />
                    )}

                    {turn.phase === 'failed' && !turn.status?.result && (
                      <p className="text-sm text-red-400">{t.statusFailed}</p>
                    )}

                    {isLatest && TERMINAL_PHASES.includes(turn.phase) && (
                      <div className="flex flex-wrap gap-2 pt-1">
                        {turn.phase === 'failed' && (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={retryLast}
                            className="gap-2"
                          >
                            <RotateCcw className="h-3 w-3" /> {t.retryFailed}
                          </Button>
                        )}
                      </div>
                    )}

                    {isLatest && TERMINAL_PHASES.includes(turn.phase) && (
                      <FeedbackRow runId={turn.runId} lang={lang} />
                    )}
                  </AssistantBubble>
                </div>
              );
            })}

            {submitting && (
              <p className="flex items-center gap-2 text-xs text-gray-400">
                <Loader2 className="h-3 w-3 animate-spin" /> {t.statusSubmitting}
              </p>
            )}
          </div>

          {showNewContent && (
            <button
              type="button"
              onClick={jumpToBottom}
              className="absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-ide-primary/50 bg-black/90 px-3 py-1.5 text-xs font-medium text-ide-primary shadow-lg hover:bg-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-ide-primary"
            >
              <ArrowDown className="h-3 w-3" /> {t.newContent}
            </button>
          )}
        </div>

        {/* Durum şeridi: kanal + mod + iptal notu */}
        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
          {activeTurn && ACTIVE_PHASES.includes(activeTurn.phase) && (
            <Badge variant="outline" className="gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              {activeTurn.phase === 'cancelling'
                ? t.statusCancelling
                : activeTurn.phase === 'started'
                  ? t.statusStarted
                  : t.statusStarting}
              {activeTurn.status?.selectedMode ? ` · ${activeTurn.status.selectedMode}` : ''}
            </Badge>
          )}
          {channel === 'live' && <span className="text-gray-600">{t.liveUpdatesOn}</span>}
          {channel === 'polling' && <span className="text-gray-600">{t.liveUpdatesOff}</span>}
        </div>

        {/* Besteci: soru girişi (çalışırken DURDUR kontrolü ayrı) */}
        {isRunActive ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void cancel()}
              disabled={activeTurn?.phase === 'cancelling' || submitting}
              className="gap-2"
            >
              <Square className="h-3 w-3" /> {t.cancel}
            </Button>
            <p className="text-xs text-gray-500">
              {activeTurn?.phase === 'cancelling' ? t.cancelRequestedNote : t.sendHint}
            </p>
          </div>
        ) : (
          <form
            className="space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              handleSubmitQuestion(question, false);
            }}
          >
            <div className="space-y-1">
              <Label htmlFor="agent-question" className="text-xs text-gray-400">
                {t.inputLabel}
              </Label>
              <Textarea
                id="agent-question"
                ref={inputRef}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  // Enter gönderir, Shift+Enter satır atlar (IME kompozisyonu korunur).
                  if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    if (canSubmit) handleSubmitQuestion(question, false);
                  }
                }}
                placeholder={t.inputPlaceholder}
                rows={2}
                maxLength={8000}
                disabled={submitting}
                aria-describedby="agent-send-hint"
                className="resize-none border-ide-border bg-black/30 text-sm text-gray-200"
              />
              <p id="agent-send-hint" className="text-[10px] text-gray-600">
                {t.sendHint}
              </p>
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
                disabled={!canSubmit}
                className="gap-2"
                size="sm"
              >
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {submitting ? t.sending : t.send}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!canSubmit}
                onClick={() => handleSubmitQuestion(question, true)}
                className="gap-2"
              >
                {t.modeDeepResearch}
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
}

function UserBubble({ text, label }: { text: string; label: string }) {
  return (
    <div className="ml-auto flex max-w-[85%] items-start justify-end gap-2">
      <div className="rounded-2xl rounded-br-sm border border-ide-primary/30 bg-ide-primary/10 px-3 py-2">
        <span className="sr-only">{label}: </span>
        <p className="whitespace-pre-wrap text-sm text-gray-100">{text || '…'}</p>
      </div>
      <span
        aria-hidden="true"
        className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-ide-primary/40 bg-ide-primary/10"
      >
        <User className="h-3.5 w-3.5 text-ide-primary" />
      </span>
    </div>
  );
}

function AssistantBubble({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mr-auto flex max-w-[95%] items-start gap-2">
      <span
        aria-hidden="true"
        className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-ide-border bg-black/40"
      >
        <Bot className="h-3.5 w-3.5 text-gray-400" />
      </span>
      <div className="min-w-0 flex-1 space-y-2 rounded-2xl rounded-bl-sm border border-ide-border bg-black/30 px-3 py-2.5">
        <span className="sr-only">{label}: </span>
        {children}
      </div>
    </div>
  );
}

/** Terminal çalışmanın izin verilen sonucu: yanıt/rapor + kaynak kartları. */
function TurnResult({
  turn,
  articleSlug,
  lang,
}: {
  turn: AgentTurn;
  articleSlug: string;
  lang: AgentLang;
}) {
  const t = agentTexts[lang];
  const result = turn.status?.result;
  if (!result) return null;

  return (
    <div className="space-y-3 border-t border-ide-border pt-2">
      {result.unavailableReason ? (
        <p className="text-sm text-amber-400">
          {t.contentUnavailable}: {result.unavailableReason}
        </p>
      ) : (
        <>
          {result.answer && (
            <div>
              <p className="mb-1 text-xs uppercase text-gray-500">{t.answerHeading}</p>
              <AgentChatMarkdown content={result.answer} />
            </div>
          )}
          {result.report && (
            <div>
              <p className="mb-1 text-xs uppercase text-gray-500">{t.reportHeading}</p>
              <AgentChatMarkdown content={result.report} />
            </div>
          )}
          {result.unresolvedQuestion && (
            <p className="text-xs text-gray-400">
              {t.unresolved}: {result.unresolvedQuestion}
            </p>
          )}
          {result.citations.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs uppercase text-gray-500">{t.sources}</p>
              <ul className="space-y-1">
                {result.citations.map((citation, index) => (
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
          className="min-h-[24px] rounded border border-ide-border px-2 py-0.5 hover:border-ide-primary hover:text-ide-primary"
        >
          {rating}
        </button>
      ))}
    </div>
  );
}
