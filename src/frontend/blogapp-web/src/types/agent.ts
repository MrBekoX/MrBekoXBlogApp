/**
 * Agent run tipleri (B10). Backend sözleşmesi: src/contracts/agent/v1
 * (payload şemaları) + B10 endpoint DTO'ları (camelCase JSON).
 * Terminal sonuç snapshot'ı backend'de AgentResultPresentationGuard'tan
 * geçmiş izin verilen alanlarla döner; maskeleme durumunda unavailableReason taşınır.
 */

export type AgentModePreference = 'auto' | 'fast' | 'analysis' | 'deep_research';

/**
 * Sohbet konusu (Who am I). Çalışma derinliği (AgentModePreference) ile AYNI
 * kavram DEĞİLDİR: konu kaynak kapsamını belirler. Eksik/bilinmeyen değer
 * istemcide 'auto' olarak okunur (eski backend/kayıt uyumu).
 */
export type AgentConversationTopic = 'auto' | 'who_am_i';

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
  /** 'profile': yayımlanmış yazar profili bölümü (/about#{sectionId}). Bilinmeyen
   * tür istemcide bağlantısız metin olarak gösterilir (toleranslı okuma). */
  kind: 'article' | 'web' | 'profile' | (string & {});
  title?: string | null;
  url?: string | null;
  articleId?: string | null;
  articleRevision?: number | null;
  chunkIndex?: number | null;
  sourceId?: string | null;
  // kind === 'profile' alanları (backend v2 sözleşmesi; camelCase DTO)
  profileId?: string | null;
  profileRevision?: number | null;
  profileContentHash?: string | null;
  sectionId?: string | null;
}

export interface AgentRunResult {
  status: string;
  selectedMode?: string | null;
  sourceScope?: string | null;
  answer?: string | null;
  report?: string | null;
  citations: AgentRunCitation[];
  unresolvedQuestion?: string | null;
  /** Sunum guard'ı maskelediyse gerekçe. Profil kodları: "profile_updated",
   * "profile_unavailable", "legacy_profile_unavailable" (yerelleştirilmiş mesaja
   * çevrilir); diğer değerler (makale guard'ı) metin olarak gösterilir. */
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
  /** Run'ın kabul anında sabitlenen konusu. Eski backend/kayıtta yoksa 'auto'
   * sayılır; geri yüklemede panel konusuyla eşleşmesi zorunludur. */
  conversationTopic?: AgentConversationTopic | string | null;
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
  /** Eksikse backend 'auto' kabul eder. who_am_i'de articleId/selectedText GÖNDERİLMEZ. */
  conversationTopic?: AgentConversationTopic;
  budgetProfile?: string;
  articleId?: string;
  selectedText?: string;
  conversationId?: string;
  idempotencyKey: string;
}

/** POST /api/v1/agent/research gövdesi (mod backend'de deep_research sabittir).
 * who_am_i ile ASLA kullanılmaz (istemci reddeder; backend 400 döner). */
export type AgentResearchRequest = Omit<AgentMessageRequest, 'modePreference'>;

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
