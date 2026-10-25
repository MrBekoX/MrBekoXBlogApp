'use client';

/**
 * Ortak agent oturumu (makale paneli + /about Who am I paneli).
 *
 * Eski ArticleAgentPanel'in davranışı aynen taşındı; saf çekirdekler lib/agent/*
 * altında birim testlidir:
 * - GERÇEK ZAMAN: SignalR AgentRunsHub ("RunUpdated"; grup run:{runId}, sahiplik
 *   backend'de). Bildirim TETİKLEYİCİDİR: adım verisi her zaman getEvents(after)
 *   commit edilmiş replay'inden okunur (run-channel.ts). Kanal kurulamazsa ya da
 *   yeniden bağlanma tükenirse SON ÇARE 4 sn yoklama.
 * - Replay sayfalama (≤25 sayfa) + monoton event_sequence filtresi (replay.ts):
 *   duplicate/geç olay adım çoğaltamaz, terminali geri çeviremez.
 * - Canlı yanıt: generation_delta parçaları foldDeltaText ile birleşir; konu
 *   canlı akışa kapalıysa (who_am_i) metin GÖSTERİLMEZ — cevap yalnız denetimli
 *   terminal sonuçtan gelir.
 * - İptal: POST cancel → "iptal isteniyor" (terminal DEĞİL) → terminal cancelled
 *   replay'den beklenir; faz birleştirme geç olayla geri dönüşü engeller.
 * - needs_input (B9): "Devam et" → beklenen input sürümüyle resume.
 * - Geri yükleme: run kimliği konu/kapsam başına ayrı anahtarda (storage.ts);
 *   GET ile backend'den doğrulanmadan (konu + makale kapsamı) HİÇBİR şey
 *   gösterilmez; 403/404 kalıcı erişilemezlikte kayıt temizlenir ve kullanıcı
 *   bilgilendirilir; geçici ağ hatasında sınırlı yeniden deneme.
 */

import { useCallback, useEffect, useEffectEvent, useRef, useState } from 'react';
import { HubConnectionBuilder, LogLevel } from '@microsoft/signalr';
import { agentApi, agentErrorMessage } from '@/lib/agent-api';
import { agentTexts, agentTopicTexts, type AgentLang } from '@/lib/agent-i18n';
import { AGENT_RUNS_HUB_URL } from '@/lib/env';
import type {
  AgentConversationTopic,
  AgentPhase,
  AgentModePreference,
  AgentRunAccepted,
  AgentRunEvent,
  AgentRunStatus,
} from '@/types/agent';
import {
  buildAgentSteps,
  deriveEventKind,
  isTerminalKind,
  isWaitingInputKind,
  type AgentStepVM,
} from '@/components/agent/agent-steps-model';
import type { AgentRequestPlan } from '@/lib/agent/topic';
import { replayEventPages } from '@/lib/agent/replay';
import { openRunChannel, type ChannelState } from '@/lib/agent/run-channel';
import { createTerminalRecovery } from '@/lib/agent/terminal-recovery';
import { createSubmissionIdentity, isDefinitiveSubmissionFailure } from '@/lib/agent/submission-identity';
import {
  httpStatusOf,
  isActivePhase,
  isTerminalPhase,
  originalModePreference,
  provisionalGraceMs,
  liveAnswerFor,
  mergePhase,
  phaseFromStatus,
  submitErrorKind,
  terminalLabel,
} from '@/lib/agent/session-model';
import {
  clearStoredRunId,
  getBrowserStorage,
  readStoredRunId,
  writeStoredRunId,
  type StorageLike,
} from '@/lib/agent/storage';

/** Yoklama fallback aralığı (yalnız SignalR hiç kurulamadığında / tükendiğinde). */
const POLL_FALLBACK_MS = 4000;
/** Replay sayfalama güvenlik üst sınırı (tek sayfa MaxPageSize=200 → ≈5000 olay). */
const MAX_EVENT_PAGES = 25;
/** Eşzamanlı ingest talepleri için en fazla ek tur. */
const MAX_INGEST_PASSES = 3;
/** Geri yüklemede geçici hata için GET denemesi (403/404 kalıcıdır, denenmez). */
const RESTORE_ATTEMPTS = 3;
const RESTORE_RETRY_MS = 1500;

/** Sohbetteki tek çalışma (soru + canlı durum + terminal sonuç). */
export interface AgentTurn {
  runId: string;
  question: string;
  isResearch: boolean;
  modePreference?: AgentModePreference;
  phase: AgentPhase;
  status: AgentRunStatus | null;
  /** Canlı yanıt: generation_delta parçalarının birleşimi (foldDeltaText).
   * Yalnız çalışma aktifken gösterilir; terminalde sonuç devralır. */
  liveAnswer?: string;
}

/** Panelin istek kurucusuna verilen gönderim girdisi. */
export interface AgentSubmitRequest {
  question: string;
  deepResearch: boolean;
  conversationId?: string;
  idempotencyKey: string;
  /** Retry keeps the original preference without changing the composer. */
  modePreference?: AgentModePreference;
}

export interface UseAgentSessionOptions {
  /** Son run kimliğinin saklandığı anahtar (konu/kapsam başına ayrı). */
  storageKey: string;
  topic: AgentConversationTopic;
  lang: AgentLang;
  /** Gönderim planı (uç nokta + gövde); konu kurallarını uygular (lib/agent/topic). */
  buildRequest: (request: AgentSubmitRequest) => AgentRequestPlan;
  /** Geri yüklenen run panelin konusu/kapsamıyla eşleşiyor mu? (backend GET'ten) */
  validateRestoredRun: (status: AgentRunStatus, storedRunId: string) => boolean;
  /** Okumadan önce tek seferlik depolama hazırlığı (ör. eski anahtar geçişi). */
  prepareStorage?: (storage: StorageLike) => void;
  /** generation_delta canlı metni gösterilsin mi? (who_am_i: false) */
  streamLiveAnswer: boolean;
}

function newIdempotencyKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function useAgentSession(options: UseAgentSessionOptions) {
  const {
    storageKey,
    topic,
    lang,
    buildRequest,
    validateRestoredRun,
    prepareStorage,
    streamLiveAnswer,
  } = options;
  const t = agentTexts[lang];
  const startedText = agentTopicTexts(lang, topic).statusStarted;

  const [turns, setTurns] = useState<AgentTurn[]>([]);
  const [steps, setSteps] = useState<AgentStepVM[]>([]);
  const [stepsOpen, setStepsOpen] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [channel, setChannel] = useState<ChannelState>('connecting');
  const [nowTick, setNowTick] = useState(() => Date.now());
  const [submitting, setSubmitting] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [finalVerificationPending, setFinalVerificationPending] = useState(false);
  const [finalVerificationUnavailable, setFinalVerificationUnavailable] = useState(false);
  const [provisionalRunId, setProvisionalRunId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);

  /** Şu an izlenen run (replay/ingest bu kimliğe kilitlidir; eski run sonucu karışmaz). */
  const currentRunIdRef = useRef<string | null>(null);
  /** Yeni run başlatıldığında artar: devam eden geri yükleme bayatlar. */
  const epochRef = useRef(0);
  /** Commit edilmiş projection'dan okunan son event_sequence (monoton imleç). */
  const lastSequenceRef = useRef(0);
  /** Authoritative GET responses can overlap; replay cursor is a separate stream. */
  const lastStatusSequenceRef = useRef(-1);
  const eventsRef = useRef<AgentRunEvent[]>([]);
  const ingestBusyRef = useRef(false);
  const ingestRerunRef = useRef(false);
  const terminalHandledRef = useRef(false);
  const terminalSeenRef = useRef(false);
  const terminalRecoveryRef = useRef<ReturnType<typeof createTerminalRecovery> | null>(null);
  const finalVerificationRef = useRef<ReturnType<typeof createTerminalRecovery> | null>(null);
  const provisionalDeadlineRef = useRef(0);
  const submissionIdentityRef = useRef(createSubmissionIdentity(newIdempotencyKey));
  const submittingOperationRef = useRef<object | null>(null);
  const startedSeenRef = useRef(false);
  /** İlk generation_delta görüldüğünde TEK kez "yazıyor" duyurusu (aria-live). */
  const deltaAnnouncedRef = useRef(false);
  const autoCollapseDoneRef = useRef(false);
  const lastAnnouncementRef = useRef('');
  /** Async geri yükleme devamında GÜNCEL dil metinleri (hydration sonrası dil değişebilir). */
  const textsRef = useRef({ t, startedText });

  useEffect(() => {
    textsRef.current = { t, startedText };
  }, [t, startedText]);

  const activeTurn = turns.length > 0 ? turns[turns.length - 1] : null;
  const activeRunId = activeTurn?.runId ?? null;
  const activeIsProvisional = !finalVerificationUnavailable && (finalVerificationPending ||
    (activeTurn?.status?.isProvisionalTerminal === true && provisionalRunId === activeRunId));
  const activeIsTerminal = activeTurn ? isTerminalPhase(activeTurn.phase) && !activeIsProvisional : false;
  const isRunActive = submitting || activeIsProvisional || (activeTurn ? isActivePhase(activeTurn.phase) : false);
  // B9 needs_input yüzeyleme: son adım girdi bekliyor ve çalışma hâlâ aktifse
  // (iptal talep edilmemişse) "Devam et" sunulur. Faz makinesi DEĞİŞMEZ; türetilmiş görünüm.
  const activeWaitingInput =
    activeTurn !== null &&
    isActivePhase(activeTurn.phase) &&
    activeTurn.phase !== 'cancelling' &&
    steps.length > 0 &&
    isWaitingInputKind(steps[steps.length - 1].kind);

  const announce = useCallback((message: string) => {
    if (lastAnnouncementRef.current === message) return;
    lastAnnouncementRef.current = message;
    setAnnouncement(message);
  }, []);

  const updateTurn = useCallback((runId: string, update: (turn: AgentTurn) => AgentTurn) => {
    setTurns((prev) => prev.map((turn) => (turn.runId === runId ? update(turn) : turn)));
  }, []);

  /** Only the current scope/run may apply an authoritative result. */
  const refreshStatus = useCallback(
    async (runId: string): Promise<AgentRunStatus | null> => {
      const epoch = epochRef.current;
      const isCurrent = () => currentRunIdRef.current === runId && epochRef.current === epoch;
      if (!isCurrent()) return null;
      try {
        const status = await agentApi.getRun(runId);
        if (!isCurrent() || !validateRestoredRun(status, runId)) return null;
        // A backend deadline terminal can precede a newer worker terminal. Keep
        // equal-sequence refreshes so publication/profile masking can still change.
        if (status.lastEventSequence < lastStatusSequenceRef.current) return null;
        const nextPhase = phaseFromStatus(status);
        const provisional = status.status === 'Failed' && status.isProvisionalTerminal === true;
        if (terminalSeenRef.current && !isTerminalPhase(nextPhase)) return null;
        if (terminalHandledRef.current && provisional) return null;
        lastStatusSequenceRef.current = status.lastEventSequence;
        updateTurn(runId, (turn) => {
          // An older overlapping GET must not erase a terminal result with Accepted.
          if (isTerminalPhase(turn.phase) && !isTerminalPhase(nextPhase)) return turn;
          return { ...turn, status, phase: mergePhase(turn.phase, nextPhase) };
        });
        if (isTerminalPhase(nextPhase)) {
          terminalSeenRef.current = true;
          terminalHandledRef.current = !provisional;
          setFinalVerificationUnavailable(false);
          if (provisional) {
            const grace = provisionalGraceMs(status);
            const candidate = performance.now() + grace;
            provisionalDeadlineRef.current = provisionalDeadlineRef.current > 0
              ? Math.min(provisionalDeadlineRef.current, candidate) : candidate;
            if (provisionalDeadlineRef.current > performance.now()) {
              setProvisionalRunId(runId);
              finalVerificationRef.current?.dispose();
              finalVerificationRef.current = null;
              setFinalVerificationPending(false);
            } else {
              setProvisionalRunId(null);
              setFinalVerificationPending(true);
            }
          }
          if (!provisional) {
            terminalRecoveryRef.current?.dispose();
            terminalRecoveryRef.current = null;
            finalVerificationRef.current?.dispose();
            finalVerificationRef.current = null;
            provisionalDeadlineRef.current = 0;
            setProvisionalRunId(null);
            setFinalVerificationPending(false);
          }
          announce(provisional ? t.statusReconciling : terminalLabel(nextPhase, t));
          // Terminalde adım alanı bir kez otomatik kapanır (kullanıcı açabilir).
          if (runId === currentRunIdRef.current && !autoCollapseDoneRef.current) {
            autoCollapseDoneRef.current = true;
            setStepsOpen(false);
          }
        } else if (nextPhase === 'started') {
          announce(startedText);
        }
        return status;
      } catch (err) {
        if (!isCurrent()) return null;
        const status = httpStatusOf(err);
        if (status === 403 || status === 404) {
          terminalRecoveryRef.current?.dispose();
          terminalRecoveryRef.current = null;
          finalVerificationRef.current?.dispose();
          finalVerificationRef.current = null;
          setFinalVerificationPending(false);
          setProvisionalRunId(null);
          currentRunIdRef.current = null;
          epochRef.current += 1;
          const storage = getBrowserStorage();
          if (storage) clearStoredRunId(storage, storageKey, runId);
          setTurns((previous) => previous.filter((turn) => turn.runId !== runId));
          setSteps([]);
          setConversationId(undefined);
          const message = status === 403 ? t.runForbidden : t.runNotFound;
          setError(message);
          announce(message);
        }
        return null;
      }
    },
    [announce, startedText, storageKey, t, updateTurn, validateRestoredRun],
  );

  const verifyFinalResult = useCallback(async (runId: string) => {
    if (currentRunIdRef.current !== runId || terminalHandledRef.current) return;
    const epoch = epochRef.current;
    terminalRecoveryRef.current?.dispose();
    terminalRecoveryRef.current = null;
    setFinalVerificationPending(true);
    setProvisionalRunId((current) => current === runId ? null : current);
    setFinalVerificationUnavailable(false);
    if (!finalVerificationRef.current) {
      finalVerificationRef.current = createTerminalRecovery({
        isCurrent: () => currentRunIdRef.current === runId && epochRef.current === epoch,
        refresh: async () => {
          const status = await refreshStatus(runId);
          return status !== null && isTerminalPhase(phaseFromStatus(status)) && status.isProvisionalTerminal !== true;
        },
        maxAttempts: 3,
        retryDelaysMs: [750, 1500],
        onExhausted: () => {
          finalVerificationRef.current = null;
          setFinalVerificationPending(false);
          setFinalVerificationUnavailable(true);
          announce(t.finalVerificationUnavailable);
        },
      });
    }
    await finalVerificationRef.current.start();
  }, [announce, refreshStatus, t]);

  const reconcileTerminal = useCallback(async (runId: string) => {
    if (terminalHandledRef.current || currentRunIdRef.current !== runId) return;
    if (finalVerificationRef.current) return;
    if (!terminalRecoveryRef.current) {
      const epoch = epochRef.current;
      terminalRecoveryRef.current = createTerminalRecovery({
        isCurrent: () => currentRunIdRef.current === runId && epochRef.current === epoch,
        refresh: async () => {
          const status = await refreshStatus(runId);
          return status !== null && isTerminalPhase(phaseFromStatus(status)) && status.isProvisionalTerminal !== true;
        },
      });
    }
    await terminalRecoveryRef.current.start();
  }, [refreshStatus]);

  /** Yeni projection olaylarını monoton filtreyle al; adımları GERÇEK olaylardan kur. */
  const ingestEvents = useCallback(
    async (runId: string) => {
      if (runId !== currentRunIdRef.current) return; // eski run'ın geç tetiklemesi
      if (ingestBusyRef.current) {
        ingestRerunRef.current = true;
        return;
      }
      ingestBusyRef.current = true;
      try {
        for (let pass = 0; pass < MAX_INGEST_PASSES; pass += 1) {
          const target = currentRunIdRef.current;
          if (!target) break;
          ingestRerunRef.current = false;

          const outcome = await replayEventPages({
            fetchPage: (after) => agentApi.getEvents(target, after),
            getCursor: () => lastSequenceRef.current,
            setCursor: (sequence) => {
              lastSequenceRef.current = sequence;
            },
            isStale: () => currentRunIdRef.current !== target,
            maxPages: MAX_EVENT_PAGES,
            onFresh: async (fresh) => {
              eventsRef.current = [...eventsRef.current, ...fresh];
              setSteps(buildAgentSteps(eventsRef.current));
              // Canlı yanıt: delta parçalarının birleşimi her ingest'te tazelenir.
              const liveAnswer = liveAnswerFor(eventsRef.current, streamLiveAnswer);
              updateTurn(target, (turn) => (turn.liveAnswer === liveAnswer ? turn : { ...turn, liveAnswer }));

              // İlk delta'da TEK erişilebilirlik duyurusu; chunk başına duyuru yok.
              if (
                streamLiveAnswer &&
                !deltaAnnouncedRef.current &&
                fresh.some((event) => event.kind === 'generation_delta')
              ) {
                deltaAnnouncedRef.current = true;
                announce(t.statusGenerating);
              }

              if (!startedSeenRef.current) {
                startedSeenRef.current = true;
                updateTurn(target, (turn) => ({ ...turn, phase: mergePhase(turn.phase, 'started') }));
                announce(startedText);
              }

              const sawTerminal = fresh.some((event) => {
                const kind = deriveEventKind(event);
                return kind !== null && isTerminalKind(kind);
              });
              if (sawTerminal && !terminalHandledRef.current) {
                // Terminal sonucu guard'lı GET'ten tazele (push maskeli olabilir).
                await reconcileTerminal(target);
              }
            },
          });

          // Yeni run başladıysa bayat sayfa uygulanmadı: yeni run için yeniden oku.
          if (outcome === 'stale') ingestRerunRef.current = true;
          // Bu tur sırasında gelen tetikleme varsa (bildirim/yoklama) bir tur daha.
          if (!ingestRerunRef.current) break;
        }
      } catch {
        // Tek replay okuma hatası: sonraki bildirim/yoklama yeniden dener.
      } finally {
        ingestBusyRef.current = false;
      }
    },
    [announce, reconcileTerminal, startedText, streamLiveAnswer, t, updateTurn],
  );

  // Sayfa yenileme sonrası geri dönüş: bu konu/kapsam için kayıtlı SON run.
  // Backend GET doğrulaması (konu + kapsam) geçmeden hiçbir şey gösterilmez.
  const restoreFromStorage = useEffectEvent(async (key: string, signal: { cancelled: boolean }) => {
    const storage = getBrowserStorage();
    if (!storage) return;
    try {
      prepareStorage?.(storage);
    } catch {
      // geçiş en iyi çabadır; okuma sürer
    }
    const runId = readStoredRunId(storage, key);
    if (!runId) return;

    const epoch = epochRef.current;
    const isStale = () => signal.cancelled || epochRef.current !== epoch;

    let status: AgentRunStatus | null = null;
    for (let attempt = 0; attempt < RESTORE_ATTEMPTS && status === null; attempt += 1) {
      try {
        status = await agentApi.getRun(runId);
      } catch (err) {
        if (isStale()) return;
        const httpStatus = httpStatusOf(err);
        // KALICI erişilemezlik (403: başka oturum / 404: kayıt yok): kayıt temizlenir,
        // besteci açık kalır ve kullanıcı bilgilendirilir.
        if (httpStatus === 403 || httpStatus === 404) {
          clearStoredRunId(storage, key, runId);
          const texts = textsRef.current.t;
          const message = httpStatus === 403 ? texts.runForbidden : texts.runNotFound;
          setError(message);
          announce(message);
          return;
        }
        if (attempt < RESTORE_ATTEMPTS - 1) await delay(RESTORE_RETRY_MS * (attempt + 1));
      }
      if (isStale()) return;
    }
    if (!status || isStale()) return;

    // Konu/kapsam uyuşmazlığı: kayıt düşürülür, hiçbir şey yüklenmez (sızıntı yok).
    if (!validateRestoredRun(status, runId)) {
      clearStoredRunId(storage, key, runId);
      return;
    }

    const phase = phaseFromStatus(status);
    const terminal = isTerminalPhase(phase);
    currentRunIdRef.current = runId;
    lastSequenceRef.current = 0;
    lastStatusSequenceRef.current = status.lastEventSequence;
    eventsRef.current = [];
    const provisional = terminal && status.isProvisionalTerminal === true;
    provisionalDeadlineRef.current = provisional ? performance.now() + provisionalGraceMs(status) : 0;
    setProvisionalRunId(provisional && provisionalGraceMs(status) > 0 ? runId : null);
    setFinalVerificationPending(provisional && provisionalGraceMs(status) === 0);
    setFinalVerificationUnavailable(false);
    terminalHandledRef.current = terminal && !provisional;
    terminalSeenRef.current = terminal;
    startedSeenRef.current = terminal;
    deltaAnnouncedRef.current = false;
    autoCollapseDoneRef.current = terminal;
    ingestRerunRef.current = false;

    setConversationId(status.conversationId || undefined);
    setSteps([]);
    // Çalışma sürerken adım alanı açık başlar; terminal kayıt kapalı gelir.
    setStepsOpen(!terminal);
    const preference = originalModePreference(status);
    setTurns([{ runId, question: status.question ?? '', isResearch: preference === 'deep_research',
      modePreference: preference, phase, status }]);
    const latest = textsRef.current;
    if (terminal) announce(provisional ? latest.t.statusReconciling : terminalLabel(phase, latest.t));
    else if (phase === 'started') announce(latest.startedText);

    await ingestEvents(runId);
  });

  useEffect(() => {
    const signal = { cancelled: false };
    const submissionIdentity = submissionIdentityRef.current;
    void restoreFromStorage(storageKey, signal);
    return () => {
      signal.cancelled = true;
      epochRef.current += 1;
      currentRunIdRef.current = null;
      terminalRecoveryRef.current?.dispose();
      terminalRecoveryRef.current = null;
      finalVerificationRef.current?.dispose();
      finalVerificationRef.current = null;
      submissionIdentity.clear();
      submittingOperationRef.current = null;
    };
  }, [storageKey]);

  // GERÇEK ZAMAN: SignalR AgentRunsHub. Bildirim tetikleyicidir; veri replay'den.
  useEffect(() => {
    const runId = activeRunId;
    if (!runId || activeIsTerminal) return;

    const connection = new HubConnectionBuilder()
      .withUrl(AGENT_RUNS_HUB_URL, { withCredentials: true })
      .configureLogging(LogLevel.Warning)
      .withAutomaticReconnect()
      .build();

    return openRunChannel({
      runId,
      connection,
      getLastSequence: () => lastSequenceRef.current,
      ingest: () => ingestEvents(runId),
      refresh: () => refreshStatus(runId),
      setChannel,
      pollMs: POLL_FALLBACK_MS,
    });
  }, [activeRunId, activeIsTerminal, ingestEvents, refreshStatus]);

  // Use monotonic relative time. At expiry obtain a stable authoritative result:
  // a terminal admitted before the cutoff may still be committing under its lock.
  useEffect(() => {
    if (!activeIsProvisional || !activeRunId || finalVerificationUnavailable) return;
    const timer = setTimeout(() => {
      setNowTick(Date.now());
      void verifyFinalResult(activeRunId);
    }, Math.max(provisionalDeadlineRef.current - performance.now(), 0));
    return () => clearTimeout(timer);
  }, [activeIsProvisional, activeRunId, activeTurn?.status, finalVerificationUnavailable, verifyFinalResult]);

  // Çalışan adım için canlı elapsed saati (yalnız gerçekten çalışırken).
  const hasSteps = steps.length > 0;
  useEffect(() => {
    if (!isRunActive || !hasSteps) return;
    const timer = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [isRunActive, hasSteps]);

  const startRun = useCallback(
    (accepted: AgentRunAccepted, questionText: string, isResearch: boolean, preference: AgentModePreference) => {
      // Yeni çalışma: replay imlecini sıfırla; devam eden geri yükleme bayatlar.
      epochRef.current += 1;
      terminalRecoveryRef.current?.dispose();
      terminalRecoveryRef.current = null;
      finalVerificationRef.current?.dispose();
      finalVerificationRef.current = null;
      provisionalDeadlineRef.current = 0;
      setProvisionalRunId(null);
      setFinalVerificationPending(false);
      setFinalVerificationUnavailable(false);
      currentRunIdRef.current = accepted.runId;
      lastSequenceRef.current = 0;
      lastStatusSequenceRef.current = -1;
      eventsRef.current = [];
      terminalHandledRef.current = false;
      terminalSeenRef.current = false;
      startedSeenRef.current = false;
      deltaAnnouncedRef.current = false;
      autoCollapseDoneRef.current = false;
      ingestRerunRef.current = false;
      setSteps([]);
      setStepsOpen(true);
      setConversationId(accepted.conversationId);
      const storage = getBrowserStorage();
      if (storage) writeStoredRunId(storage, storageKey, accepted.runId);
      setTurns((prev) => [
        ...prev,
        { runId: accepted.runId, question: questionText, isResearch, modePreference: preference, phase: 'accepted', status: null },
      ]);
    },
    [storageKey],
  );

  /** Soru gönderir; kabul edilirse true (çağıran besteciyi temizler). */
  const submit = useCallback(
    async (questionText: string, deepResearch: boolean, retryPreference?: AgentModePreference): Promise<boolean> => {
      const trimmed = questionText.trim();
      if (!trimmed || submittingOperationRef.current || submitting || isRunActive) return false;

      const candidate = buildRequest({
        question: trimmed,
        deepResearch,
        conversationId,
        idempotencyKey: '', // Assigned once for this exact logical operation below.
        modePreference: retryPreference,
      });
      if (!candidate.ok) {
        if (candidate.reason === 'research_not_allowed_for_topic') {
          setError(t.researchNotAllowed);
          announce(t.researchNotAllowed);
        }
        return false;
      }

      const plan = submissionIdentityRef.current.prepare(candidate);
      const operation = {};
      submittingOperationRef.current = operation;
      // User intent invalidates any in-flight restoration before the POST resolves.
      const epoch = ++epochRef.current;
      const isCurrent = () => epochRef.current === epoch && submittingOperationRef.current === operation;

      setSubmitting(true);
      setError(null);
      announce(t.statusSubmitting);

      try {
        const accepted =
          plan.endpoint === 'research'
            ? await agentApi.startResearch(plan.body)
            : await agentApi.sendMessage(plan.body);

        if (!isCurrent()) return false;
        submissionIdentityRef.current.complete(plan);
        startRun(accepted, trimmed, deepResearch,
          plan.endpoint === 'research' ? 'deep_research' : plan.body.modePreference);
        announce(t.statusAccepted);

        // Kabul hemen projection'a düşmüş olabilir; ilk replay'i çek.
        void refreshStatus(accepted.runId);
        void ingestEvents(accepted.runId);
        return true;
      } catch (err) {
        if (!isCurrent()) return false;
        if (isDefinitiveSubmissionFailure(err)) submissionIdentityRef.current.complete(plan);
        if (submitErrorKind(err, topic) === 'capability_unavailable') {
          // who_am_i kapasitesi kapalı (503): normal sohbete sessiz düşüş YOK.
          setError(t.whoAmIUnavailable);
          announce(t.whoAmIUnavailable);
        } else {
          setError(agentErrorMessage(err, t.errorGeneric));
          announce(t.errorGeneric);
        }
        return false;
      } finally {
        if (submittingOperationRef.current === operation) {
          submittingOperationRef.current = null;
          setSubmitting(false);
        }
      }
    },
    [
      announce,
      buildRequest,
      conversationId,
      ingestEvents,
      isRunActive,
      refreshStatus,
      startRun,
      submitting,
      t,
      topic,
    ],
  );

  const cancel = useCallback(async () => {
    const runId = activeRunId;
    if (!runId) return;
    if (!window.confirm(t.cancelConfirm)) return;
    try {
      await agentApi.cancelRun(runId);
      // "requested" TERMİNAL DEĞİLDİR (B7): iptal isteniyor gösterilir; sahte
      // "iptal edildi" YAZILMAZ — terminal cancelled olayı replay'den gelir.
      updateTurn(runId, (turn) => ({ ...turn, phase: mergePhase(turn.phase, 'cancelling') }));
      announce(t.cancelRequestedNote);
    } catch (err) {
      setError(agentErrorMessage(err, t.errorGeneric));
    }
  }, [activeRunId, announce, t, updateTurn]);

  /** Başarısız terminalde TEKRAR DENE: son soruyu yeniden gönderir. */
  const retryLast = useCallback((): Promise<boolean> => {
    if (!activeTurn || activeTurn.phase !== 'failed' || finalVerificationUnavailable) return Promise.resolve(false);
    const text = activeTurn.question || activeTurn.status?.question || '';
    if (!text.trim()) return Promise.resolve(false);
    const preference = activeTurn.modePreference ?? (activeTurn.status
      ? originalModePreference(activeTurn.status) : activeTurn.isResearch ? 'deep_research' : 'auto');
    return submit(text, preference === 'deep_research', preference);
  }, [activeTurn, finalVerificationUnavailable, submit]);

  /** B9 needs_input: beklenen input sürümü (needs_input olayının event_sequence'i)
   * doğrulanarak devam isteği. Çalışma terminal olmadığından abonelik sürer. */
  const resumeRun = useCallback(
    async (runId: string, expectedInputVersion: number) => {
      if (resuming) return;
      setResuming(true);
      setError(null);
      announce(t.resumeHint);
      try {
        await agentApi.resumeRun(runId, { expectedInputVersion });
      } catch (err) {
        setError(agentErrorMessage(err, t.errorGeneric));
        announce(t.errorGeneric);
      } finally {
        setResuming(false);
      }
    },
    [announce, resuming, t],
  );

  const toggleSteps = useCallback(() => setStepsOpen((prev) => !prev), []);

  return {
    t,
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
    activeIsTerminal,
    activeIsProvisional,
    finalVerificationUnavailable,
    checkFinalResult: () => activeRunId ? verifyFinalResult(activeRunId) : Promise.resolve(),
    isRunActive,
    activeWaitingInput,
    submit,
    cancel,
    retryLast,
    resumeRun,
  };
}

export type AgentSession = ReturnType<typeof useAgentSession>;
