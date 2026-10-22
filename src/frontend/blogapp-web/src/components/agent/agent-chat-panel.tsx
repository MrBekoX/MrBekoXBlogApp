'use client';

/**
 * Ortak agent sohbet paneli (makale paneli ve /about Who am I paneli).
 *
 * Davranış useAgentSession'dadır (SignalR + replay + yoklama, iptal, resume,
 * geri yükleme); bu bileşen görünüm + besteci durumunu taşır:
 * - Sohbet: kullanıcı + agent balonları; agent yanıtı react-markdown zinciri.
 * - Canlı işlem adımları yalnız GERÇEK olaylardan; canlı yanıt yalnız konu
 *   akışa açıksa (who_am_i'de cevap denetimli terminal sonuçtan gelir).
 * - Kontroller: Enter gönder / Shift+Enter satır (IME kompozisyonu korunur);
 *   çalışırken İPTAL; başarısız terminalde TEKRAR DENE; boş sohbet önerileri.
 * - Kaydırma: kullanıcı en alttayken otomatik takip; yukarıdaysa "Yeni içerik".
 * - Erişilebilirlik: aria-live durum bildirimi, useId tabanlı benzersiz DOM
 *   kimlikleri (iki panel aynı sayfada çakışmaz), prefers-reduced-motion, mobil
 *   tek kolon.
 * - Konu kuralları: makale bağlamı kutusu ve "Derin araştırma" yalnız auto'da;
 *   who_am_i isteği articleId/selectedText taşımaz (lib/agent/topic).
 */

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ArrowDown,
  BookOpen,
  Bot,
  ExternalLink,
  Globe,
  Loader2,
  Play,
  RotateCcw,
  Send,
  Square,
  User,
  UserRound,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { agentApi } from '@/lib/agent-api';
import { agentTexts, agentTopicTexts, type AgentLang } from '@/lib/agent-i18n';
import {
  buildAgentRequest,
  topicAllowsArticleContext,
  topicAllowsResearch,
  topicStreamsLiveAnswer,
} from '@/lib/agent/topic';
import { resolveCitationLink } from '@/lib/agent/citations';
import {
  isActivePhase,
  isTerminalPhase,
  unavailableMessage,
  validateRestoredRun,
  type RestoreScope,
} from '@/lib/agent/session-model';
import type { StorageLike } from '@/lib/agent/storage';
import { useAgentSession, type AgentSubmitRequest, type AgentTurn } from '@/hooks/use-agent-session';
import type {
  AgentConversationTopic,
  AgentModePreference,
  AgentRunCitation,
  AgentRunStatus,
} from '@/types/agent';
import { AgentChatMarkdown } from './agent-chat-markdown';
import { AgentStepsPanel } from './agent-steps';

export interface AgentChatPanelProps {
  lang: AgentLang;
  topic: AgentConversationTopic;
  /** Son run kimliğinin saklandığı anahtar (lib/agent/storage). */
  storageKey: string;
  /** Geri yüklemede backend run'ının eşleşmesi gereken konu/kapsam. */
  restoreScope: RestoreScope;
  /** Makale bağlamı (yalnız auto konusunda kullanılır; kaynak kartı slug'ı). */
  article?: { articleId: string; articleSlug: string };
  /** Okumadan önce tek seferlik depolama hazırlığı (eski anahtar geçişi). */
  prepareStorage?: (storage: StorageLike) => void;
  /** Çalışma etkinliği değişince üst bileşene bildirilir (konu kilidi). */
  onRunActiveChange?: (active: boolean) => void;
}

export function AgentChatPanel({
  lang,
  topic,
  storageKey,
  restoreScope,
  article,
  prepareStorage,
  onRunActiveChange,
}: AgentChatPanelProps) {
  const t = agentTexts[lang];
  const topicTexts = agentTopicTexts(lang, topic);
  const streamLiveAnswer = topicStreamsLiveAnswer(topic);
  const showArticleContext = Boolean(article) && topicAllowsArticleContext(topic);
  const showResearch = topicAllowsResearch(topic);

  const questionId = useId();
  const hintId = useId();
  const modeId = useId();

  const [question, setQuestion] = useState('');
  const [modePreference, setModePreference] = useState<AgentModePreference>('auto');
  const [includeArticleContext, setIncludeArticleContext] = useState(true);
  const [showNewContent, setShowNewContent] = useState(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const atBottomRef = useRef(true);

  const articleId = article?.articleId;
  const buildRequest = useCallback(
    (request: AgentSubmitRequest) =>
      buildAgentRequest({
        topic,
        question: request.question,
        language: lang,
        modePreference,
        deepResearch: request.deepResearch,
        idempotencyKey: request.idempotencyKey,
        conversationId: request.conversationId,
        articleId: includeArticleContext ? articleId : undefined,
      }),
    [articleId, includeArticleContext, lang, modePreference, topic],
  );

  const validateRestore = useCallback(
    (status: AgentRunStatus, storedRunId: string) => validateRestoredRun(status, storedRunId, restoreScope).ok,
    [restoreScope],
  );

  const session = useAgentSession({
    storageKey,
    topic,
    lang,
    buildRequest,
    validateRestoredRun: validateRestore,
    prepareStorage,
    streamLiveAnswer,
  });
  const {
    turns,
    steps,
    stepsOpen,
    toggleSteps,
    announcement,
    error,
    channel,
    nowTick,
    submitting,
    resuming,
    activeTurn,
    isRunActive,
    activeWaitingInput,
  } = session;

  useEffect(() => {
    onRunActiveChange?.(isRunActive);
  }, [isRunActive, onRunActiveChange]);

  // Takip: kullanıcı en alttaysa yeni içeriğe otomatik kaydır; değilse pill göster.
  const lastResult = activeTurn?.status?.result ?? null;
  // Canlı yanıt büyüdükçe de takip tetiklensin (yalnız uzunluk değişiminde).
  const liveAnswerLength = activeTurn?.liveAnswer?.length ?? 0;
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (atBottomRef.current) {
      el.scrollTo({ top: el.scrollHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
      return;
    }
    const frame = requestAnimationFrame(() => setShowNewContent(true));
    return () => cancelAnimationFrame(frame);
  }, [steps.length, turns.length, lastResult, liveAnswerLength]);

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

  const clearOnAccept = (accepted: boolean) => {
    if (accepted) setQuestion('');
  };

  const handleSubmitQuestion = (text: string, deepResearch: boolean) => {
    if (text.trim().length === 0) return;
    void session.submit(text, deepResearch).then(clearOnAccept);
  };

  const askAgain = (turn: AgentTurn) => {
    const text = turn.question || turn.status?.question || '';
    if (!text.trim()) return;
    void session.submit(text, false).then(clearOnAccept);
  };

  return (
    <div className="space-y-4" data-testid="agent-chat" data-topic={topic}>
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
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-gray-600">{t.suggestionsLabel}</span>
                {topicTexts.suggestions.map((suggestion) => (
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
            const runActive = isLatest && isActivePhase(turn.phase);
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
                      onToggle={toggleSteps}
                      now={nowTick}
                    />
                  ) : null}

                  {/* Canlı yanıt: generation_delta parçalarının birleşimi. Yalnız
                      çalışma aktifken ve konu akışa açıkken; terminalde TurnResult
                      devralır (metin iki kez basılmaz). Duyuru yalnız İLK delta'da
                      tek kez yapılır, bu yüzden akış kapsayıcısı aria-live TAŞIMAZ. */}
                  {streamLiveAnswer && runActive && turn.liveAnswer ? (
                    <div data-testid="agent-live-answer" className="space-y-1 border-t border-ide-border pt-2">
                      <p className="flex items-center gap-1.5 text-xs uppercase text-gray-500">
                        {t.answerHeading}
                        <span className="flex items-center gap-1.5 normal-case text-gray-400">
                          <span
                            aria-hidden="true"
                            className="h-1.5 w-1.5 rounded-full bg-ide-primary motion-safe:animate-pulse"
                          />
                          {t.statusGenerating}
                        </span>
                      </p>
                      <AgentChatMarkdown content={turn.liveAnswer} />
                    </div>
                  ) : null}

                  {runActive && steps.length === 0 && (
                    <p className="flex items-center gap-2 text-xs text-gray-400">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      {turn.phase === 'accepted' || turn.phase === 'starting'
                        ? t.statusAccepted
                        : topicTexts.statusStarted}
                    </p>
                  )}

                  {/* Who am I: cevap yalnız kaynak/politika denetimli terminal sonuçtan gelir. */}
                  {!streamLiveAnswer && runActive && turn.phase !== 'cancelling' && (
                    <p className="text-[11px] text-gray-500">{t.whoAmIVerifiedAnswerNote}</p>
                  )}

                  {turn.phase === 'cancelling' && (
                    <p className="flex items-center gap-2 text-xs text-amber-400">
                      <Loader2 className="h-3 w-3 animate-spin" /> {t.statusCancelling}
                    </p>
                  )}

                  {/* B9: agent ek girdi bekliyor — çalışma terminal değil, devam ettirilebilir */}
                  {isLatest && activeWaitingInput && (
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void session.resumeRun(turn.runId, steps[steps.length - 1].sequence)}
                        disabled={resuming}
                        className="gap-2"
                      >
                        {resuming ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                        {t.resumeAction}
                      </Button>
                      <p className="text-xs text-amber-400">{t.statusNeedsInput}</p>
                    </div>
                  )}

                  {/* Resume reddi (ör. eski sürüm) çalışırken form gizli olduğundan burada gösterilir */}
                  {isLatest && activeWaitingInput && error && (
                    <p role="alert" className="text-xs text-red-400">
                      {error}
                    </p>
                  )}

                  {/* Terminal sonuç: izin verilen sonuç (maskeleme gerekçesi dahil) */}
                  {turn.status?.result && isTerminalPhase(turn.phase) && (
                    <TurnResult
                      turn={turn}
                      articleSlug={article?.articleSlug}
                      lang={lang}
                      canAskAgain={isLatest && !isRunActive}
                      onAskAgain={() => askAgain(turn)}
                    />
                  )}

                  {turn.phase === 'failed' && !turn.status?.result && (
                    <p className="text-sm text-red-400">{t.statusFailed}</p>
                  )}

                  {isLatest && isTerminalPhase(turn.phase) && turn.phase === 'failed' && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void session.retryLast().then(clearOnAccept)}
                        className="gap-2"
                      >
                        <RotateCcw className="h-3 w-3" /> {t.retryFailed}
                      </Button>
                    </div>
                  )}

                  {isLatest && isTerminalPhase(turn.phase) && (
                    <FeedbackRow key={turn.runId} runId={turn.runId} lang={lang} />
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
        {activeTurn && isActivePhase(activeTurn.phase) && (
          <Badge variant="outline" className="gap-1">
            {!activeWaitingInput && <Loader2 className="h-3 w-3 animate-spin" />}
            {activeTurn.phase === 'cancelling'
              ? t.statusCancelling
              : activeWaitingInput
                ? t.statusNeedsInput
                : activeTurn.phase === 'started'
                  ? topicTexts.statusStarted
                  : t.statusStarting}
            {activeTurn.status?.selectedMode ? ` · ${activeTurn.status.selectedMode}` : ''}
          </Badge>
        )}
        {channel === 'live' && <span className="text-gray-600">{t.liveUpdatesOn}</span>}
        {channel === 'polling' && <span className="text-gray-600">{t.liveUpdatesOff}</span>}
      </div>

      {/* Besteci: soru girişi (çalışırken İPTAL kontrolü ayrı) */}
      {isRunActive ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void session.cancel()}
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
            <Label htmlFor={questionId} className="text-xs text-gray-400">
              {t.inputLabel}
            </Label>
            <Textarea
              id={questionId}
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
              placeholder={topicTexts.placeholder}
              rows={2}
              maxLength={8000}
              disabled={submitting}
              aria-describedby={hintId}
              className="resize-none border-ide-border bg-black/30 text-sm text-gray-200"
            />
            <p id={hintId} className="text-[10px] text-gray-600">
              {t.sendHint}
            </p>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1">
              <Label htmlFor={modeId} className="text-xs text-gray-400">
                {t.modeLabel}
              </Label>
              <select
                id={modeId}
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

          {showArticleContext && (
            <label className="flex items-center gap-2 text-xs text-gray-400">
              <input
                type="checkbox"
                checked={includeArticleContext}
                onChange={(event) => setIncludeArticleContext(event.target.checked)}
                className="accent-ide-primary"
              />
              {t.includeArticleContext}
            </label>
          )}

          {topic === 'who_am_i' && <p className="text-[11px] text-gray-500">{t.whoAmIScopeNote}</p>}

          {error && (
            <p role="alert" className="text-xs text-red-400">
              {error}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={!canSubmit} className="gap-2" size="sm">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {submitting ? t.sending : t.send}
            </Button>
            {showResearch && (
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
            )}
          </div>
        </form>
      )}
    </div>
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
  canAskAgain,
  onAskAgain,
}: {
  turn: AgentTurn;
  articleSlug?: string;
  lang: AgentLang;
  canAskAgain: boolean;
  onAskAgain: () => void;
}) {
  const t = agentTexts[lang];
  const result = turn.status?.result;
  if (!result) return null;

  if (result.unavailableReason) {
    const unavailable = unavailableMessage(result.unavailableReason, t);
    const hasQuestion = Boolean((turn.question || turn.status?.question || '').trim());
    return (
      <div className="space-y-2 border-t border-ide-border pt-2">
        <p className="text-sm text-amber-400">{unavailable.message}</p>
        {unavailable.askAgain && canAskAgain && hasQuestion && (
          <Button type="button" variant="outline" size="sm" onClick={onAskAgain} className="gap-2">
            <RotateCcw className="h-3 w-3" /> {t.askAgain}
          </Button>
        )}
      </div>
    );
  }

  const citations = Array.isArray(result.citations) ? result.citations : [];
  return (
    <div className="space-y-3 border-t border-ide-border pt-2">
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
      {citations.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs uppercase text-gray-500">{t.sources}</p>
          <ul className="space-y-1">
            {citations.map((citation, index) => (
              <li key={`${citation.sourceId ?? citation.url ?? index}-${index}`}>
                <SourceCard citation={citation} articleSlug={articleSlug} lang={lang} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

const SOURCE_LINK_CLASS =
  'flex flex-wrap items-center gap-2 rounded border border-ide-border px-2 py-1 text-xs text-gray-300 hover:border-ide-primary hover:text-ide-primary';

/** Kaynak kartı: profil → /about#bölüm; makale → /posts/{slug}#bölüm; web → yalnız http(s). */
function SourceCard({
  citation,
  articleSlug,
  lang,
}: {
  citation: AgentRunCitation;
  articleSlug?: string;
  lang: AgentLang;
}) {
  const t = agentTexts[lang];
  const link = resolveCitationLink(citation, { articleSlug });

  switch (link.type) {
    case 'profile':
      return (
        <Link href={link.href} className={SOURCE_LINK_CLASS}>
          <UserRound className="h-3 w-3" aria-hidden="true" />
          <span>{link.title ?? t.sourceProfileSection}</span>
          <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
            {t.sourceProfile}
          </Badge>
          <span className="text-gray-600">#{link.sectionId}</span>
        </Link>
      );
    case 'article':
      return (
        <Link href={link.href} className={SOURCE_LINK_CLASS}>
          <BookOpen className="h-3 w-3" aria-hidden="true" />
          <span>{link.title ?? t.sourceArticle}</span>
          {link.section && <span className="text-gray-600">#{link.section}</span>}
        </Link>
      );
    case 'external':
      return (
        <a href={link.href} target="_blank" rel="noopener noreferrer nofollow" className={SOURCE_LINK_CLASS}>
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
          <span>{link.title ?? link.href}</span>
        </a>
      );
    default: {
      const fallbackTitle =
        link.kind === 'profile' ? t.sourceProfileSection : link.kind === 'article' ? t.sourceArticle : t.sourceWeb;
      const Icon = link.kind === 'profile' ? UserRound : link.kind === 'article' ? BookOpen : Globe;
      return (
        <span className="flex flex-wrap items-center gap-2 rounded border border-ide-border/60 px-2 py-1 text-xs text-gray-500">
          <Icon className="h-3 w-3" aria-hidden="true" />
          <span>{link.title ?? fallbackTitle}</span>
          {link.kind === 'profile' && (
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              {t.sourceProfile}
            </Badge>
          )}
          {link.detail && <span className="text-gray-600">{link.detail}</span>}
          <span className="sr-only">({t.sourceUnlinked})</span>
        </span>
      );
    }
  }
}

function readFeedbackSent(runId: string): boolean {
  try {
    return typeof window !== 'undefined' && window.localStorage.getItem(`agent-feedback:${runId}`) === '1';
  } catch {
    return false;
  }
}

/** Terminal sonuç sonrası idempotent geri bildirim satırı (1-5 puan).
 * Yalnız istemcide (terminal tur varken) render edilir; run başına key'lenir. */
function FeedbackRow({ runId, lang }: { runId: string; lang: AgentLang }) {
  const t = agentTexts[lang];
  const [sent, setSent] = useState(() => readFeedbackSent(runId));
  const [busy, setBusy] = useState(false);

  const rate = async (rating: number) => {
    setBusy(true);
    try {
      const key =
        typeof crypto !== 'undefined' && 'randomUUID' in crypto
          ? crypto.randomUUID()
          : `${runId}-${rating}-${Date.now()}`;
      await agentApi.sendFeedback(runId, rating, key);
      try {
        window.localStorage.setItem(`agent-feedback:${runId}`, '1');
      } catch {
        // kalıcılık yalnız kolaylıktır
      }
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
