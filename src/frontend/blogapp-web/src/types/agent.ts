/**
 * Agent run tipleri (B10). Backend sözleşmesi: src/contracts/agent/v1
 * (payload şemaları) + B10 endpoint DTO'ları (camelCase JSON).
 * Terminal sonuç snapshot'ı backend'de AgentResultPresentationGuard'tan
 * geçmiş izin verilen alanlarla döner; maskeleme durumunda unavailableReason taşınır.
 */

export type AgentModePreference = 'auto' | 'fast' | 'analysis' | 'deep_research';

export type AgentRunState =
  | 'Accepted'
  | 'Completed'
  | 'PartiallyCompleted'
  | 'Failed'
  | 'Cancelled';

/** UI durum makinesi: kabul → başlama → tamamlanma AYRI gösterilir (plan B10). */
export type AgentPhase =
  | 'idle'
  | 'submitting'
  | 'accepted'   // 202 alındı; komut outbox'ta
  | 'starting'   // agent.run.accepted/mod_selected beklemede
  | 'started'    // mod seçildi / progressed olayları geliyor
  | 'completed'  // terminal başarı
  | 'partial'
  | 'failed'
  | 'cancelled'
  | 'cancelling' // cancel intent kabul edildi (terminal değil — B7)
  ;

export interface AgentRunAccepted {
  runId: string;
  conversationId: string;
  turnSequence: number;
  acceptedAt: string;
  deadlineAt: string;
  replay: boolean;
}

export interface AgentRunCitation {
  kind: 'article' | 'web';
  title?: string | null;
  url?: string | null;
  articleId?: string | null;
  articleRevision?: number | null;
  chunkIndex?: number | null;
  sourceId?: string | null;
}

export interface AgentRunResult {
  status: string;
  selectedMode?: string | null;
  sourceScope?: string | null;
  answer?: string | null;
  report?: string | null;
  citations: AgentRunCitation[];
  unresolvedQuestion?: string | null;
  unavailableReason?: string | null;
}

export interface AgentRunStatus {
  runId: string;
  conversationId: string;
  turnSequence: number;
  status: AgentRunState;
  modePreference: string;
  selectedMode?: string | null;
  sourceScope?: string | null;
  question: string;
  language: string;
  articleId?: string | null;
  acceptedAt: string;
  deadlineAt: string;
  terminalAt?: string | null;
  lastEventSequence: number;
  result?: AgentRunResult | null;
}

export interface AgentRunEvent {
  eventSequence: number;
  messageType: string;
  messageId: string;
  occurredAt: string;
  /** Ortak olay sözleşmesi: progressed'te payload.kind (ör. retrieval_started);
   * terminal olaylarda messageType'tan türetilir (completed/failed/cancelled/partial);
   * agent.action.proposed → action_proposed. Eski kayıtlarda absent olabilir. */
  kind?: string;
  /** progressed olayında inbox.ProgressMessage (kullanıcı-dostu TR cümle); terminalde null. */
  message?: string | null;
  /** progressed payload.detail (küratörlü kullanıcı-dostu alanlar); yoksa null. */
  detail?: Record<string, string> | null;
}

export interface AgentRunEvents {
  runId: string;
  runStatus: AgentRunState;
  lastEventSequence: number;
  hasMore: boolean;
  events: AgentRunEvent[];
}

export interface AgentRunCancel {
  runId: string;
  /** requested: komut outbox'ta; already_terminal: iş bitmiş; replay: açık cancel var. */
  outcome: string;
  requestedAt: string;
}

export interface AgentRunResume {
  runId: string;
  state: string;
  requestedAt: string;
}

export interface AgentFeedbackResult {
  runId: string;
  state: string;
  recordedAt: string;
}

/** Komut kabul isteği gövdesi (POST /api/v1/agent/messages). */
export interface AgentMessageRequest {
  question: string;
  language: 'tr' | 'en';
  modePreference: AgentModePreference;
  budgetProfile?: string;
  articleId?: string;
  selectedText?: string;
  conversationId?: string;
  idempotencyKey: string;
}

/** SignalR "RunUpdated" payload'ı (snake_case — B5 notifier sözleşmesi). */
export interface AgentRunNotification {
  run_id: string;
  message_id: string;
  message_type: string;
  status: string;
  event_sequence: number;
  message: string;
  occurred_at: string;
  result?: AgentRunResult | null;
}
