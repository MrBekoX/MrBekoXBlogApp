/**
 * Agent oturumu saf modeli: faz makinesi, geri yükleme doğrulaması, bildirim
 * filtresi, maskeleme gerekçesi ve gönderim hatası sınıflandırması.
 *
 * Bileşen/hook'tan bağımsızdır; node ortamında birim test edilir. Davranış
 * kaynakları: eski ArticleAgentPanel (B10) + Who am I kararları (K6/K7).
 */

import axios from 'axios';
import type { AgentTexts } from '@/lib/agent-i18n';
import type {
  AgentConversationTopic,
  AgentPhase,
  AgentRunEvent,
  AgentRunNotification,
  AgentRunStatus,
} from '@/types/agent';
import { foldDeltaText } from '@/components/agent/agent-steps-model';
import { normalizeTopic } from './topic';

export const TERMINAL_PHASES: readonly AgentPhase[] = ['completed', 'partial', 'failed', 'cancelled'];
export const ACTIVE_PHASES: readonly AgentPhase[] = ['accepted', 'starting', 'started', 'cancelling'];

export function isTerminalPhase(phase: AgentPhase): boolean {
  return TERMINAL_PHASES.includes(phase);
}

export function isActivePhase(phase: AgentPhase): boolean {
  return ACTIVE_PHASES.includes(phase);
}

/** GET /runs/{id} durumunu faz makinesine çevirir (eski panel ile aynı eşleme). */
export function phaseFromStatus(status: Pick<AgentRunStatus, 'status' | 'selectedMode'>): AgentPhase {
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
}

const ACTIVE_RANK: Partial<Record<AgentPhase, number>> = {
  idle: -2,
  submitting: -1,
  accepted: 0,
  starting: 1,
  started: 2,
  cancelling: 3,
};

/**
 * Faz birleştirme: terminal faz her zaman kazanır (sunucu terminali yetkilidir);
 * terminal olmayan güncelleme fazı GERİ ÇEVİREMEZ — ör. "iptal isteniyor"
 * (B7: requested terminal değildir) geç gelen 'started' ile silinmez, terminal
 * bir çalışma geç replay ile 'started'e dönmez.
 */
export function mergePhase(current: AgentPhase, next: AgentPhase): AgentPhase {
  if (isTerminalPhase(next)) return next;
  if (isTerminalPhase(current)) return current;
  const currentRank = ACTIVE_RANK[current] ?? -3;
  const nextRank = ACTIVE_RANK[next] ?? -3;
  return nextRank >= currentRank ? next : current;
}

export function terminalLabel(phase: AgentPhase, t: AgentTexts): string {
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

/** Geri yükleme kapsamı: panelin konusu ve (makale panelinde) makale kimliği. */
export interface RestoreScope {
  topic: AgentConversationTopic;
  /** Makale paneli için; run başka bir makaleye bağlıysa yüklenmez. */
  articleId?: string;
}

export type RestoreVerdict =
  | { ok: true }
  | { ok: false; reason: 'run_mismatch' | 'topic_mismatch' | 'article_mismatch' };

function sameId(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/**
 * Yerel kayıttan geri yüklenen run'ı backend GET cevabıyla doğrular. Konu
 * backend'in kabul anında sabitlediği değerdir (eksikse 'auto'); panel konusu
 * ile eşleşmeyen, başka run kimliği dönen veya who_am_i'de makaleye bağlı ya da
 * başka makaleye ait run YÜKLENMEZ (konu/run sızıntısı yok). Sahiplik zaten
 * backend'de doğrulanır (başka oturum → 403).
 */
export function validateRestoredRun(
  status: Pick<AgentRunStatus, 'runId' | 'conversationTopic' | 'articleId'>,
  storedRunId: string,
  scope: RestoreScope,
): RestoreVerdict {
  if (!status.runId || !sameId(status.runId, storedRunId)) {
    return { ok: false, reason: 'run_mismatch' };
  }
  if (normalizeTopic(status.conversationTopic) !== scope.topic) {
    return { ok: false, reason: 'topic_mismatch' };
  }
  const runArticleId = typeof status.articleId === 'string' ? status.articleId.trim() : '';
  if (scope.topic === 'who_am_i') {
    if (runArticleId) return { ok: false, reason: 'article_mismatch' };
    return { ok: true };
  }
  if (runArticleId && (!scope.articleId || !sameId(runArticleId, scope.articleId))) {
    return { ok: false, reason: 'article_mismatch' };
  }
  return { ok: true };
}

/**
 * SignalR "RunUpdated" bildirimi bu run için replay tetiklemeli mi? Başka run'ın
 * bildirimi ve replay imlecinden geride kalan (duplicate/geç) bildirim yok sayılır.
 */
export function shouldIngestNotification(
  payload: Pick<AgentRunNotification, 'run_id' | 'event_sequence'> | null | undefined,
  runId: string,
  lastSequence: number,
): boolean {
  if (!payload || payload.run_id !== runId) return false;
  if (typeof payload.event_sequence === 'number' && payload.event_sequence <= lastSequence) return false;
  return true;
}

/** Canlı yanıt metni; konu canlı akışa kapalıysa (who_am_i) her zaman boş. */
export function liveAnswerFor(events: AgentRunEvent[], enabled: boolean): string {
  return enabled ? foldDeltaText(events) : '';
}

const PROFILE_UNAVAILABLE_KEYS = {
  profile_updated: 'unavailableProfileUpdated',
  profile_unavailable: 'unavailableProfileUnavailable',
  legacy_profile_unavailable: 'unavailableLegacyProfile',
} as const satisfies Record<string, keyof AgentTexts>;

export interface UnavailableMessage {
  message: string;
  /** Profil sürümü/kapasitesi nedeniyle maskelendi: soruyu yeniden sormak önerilir. */
  askAgain: boolean;
}

/**
 * Sunum guard'ının maskeleme gerekçesini kullanıcı mesajına çevirir. Profil
 * kodları yerelleştirilir ve yeniden sorma önerilir; diğer (makale guard'ı)
 * gerekçeler eskisi gibi "İçerik kullanılamıyor: …" biçiminde gösterilir
 * (gerekçe zaten bu önekle başlıyorsa önek tekrarlanmaz).
 */
export function unavailableMessage(reason: string, t: AgentTexts): UnavailableMessage {
  const code = reason.trim().toLowerCase();
  if (Object.prototype.hasOwnProperty.call(PROFILE_UNAVAILABLE_KEYS, code)) {
    const key = PROFILE_UNAVAILABLE_KEYS[code as keyof typeof PROFILE_UNAVAILABLE_KEYS];
    return { message: t[key], askAgain: true };
  }
  const text = reason.trim();
  const prefix = t.contentUnavailable;
  if (text.toLowerCase().startsWith(prefix.toLowerCase())) {
    return { message: text, askAgain: false };
  }
  return { message: `${prefix}: ${text}`, askAgain: false };
}

const CAPABILITY_CODE = 'capability_unavailable';

function mentionsCapabilityCode(value: unknown): boolean {
  return typeof value === 'string' && value.toLowerCase().includes(CAPABILITY_CODE);
}

/** ApiResponse hata gövdesi "capability_unavailable" kodunu taşıyor mu? (alan adı toleranslı) */
export function isCapabilityUnavailableError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  const data = error.response?.data as Record<string, unknown> | undefined;
  if (!data || typeof data !== 'object') return false;
  const candidates: unknown[] = [data.code, data.errorCode, data.error, data.message];
  if (Array.isArray(data.errors)) candidates.push(...data.errors);
  return candidates.some(mentionsCapabilityCode);
}

/**
 * Gönderim hatası sınıfı. who_am_i için 503 (backend v2 kapalı/hazır değil) veya
 * açık capability_unavailable kodu → "Who am I şu an kullanılamıyor" (normal
 * sohbete sessiz düşüş YOK). Diğer konular mevcut genel hata yolunu kullanır.
 */
export function submitErrorKind(
  error: unknown,
  topic: AgentConversationTopic,
): 'capability_unavailable' | 'other' {
  if (topic !== 'who_am_i' || !axios.isAxiosError(error)) return 'other';
  if (error.response?.status === 503) return 'capability_unavailable';
  return isCapabilityUnavailableError(error) ? 'capability_unavailable' : 'other';
}

/** HTTP durum kodu (axios hatası değilse undefined). */
export function httpStatusOf(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined;
}
