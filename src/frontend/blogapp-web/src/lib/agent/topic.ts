/**
 * Sohbet konusu (Who am I) ve istek gövdesi kurucu — saf fonksiyonlar.
 *
 * Kurallar (decisions K1/K6/K7):
 * - conversationTopic: 'auto' | 'who_am_i'; bilinmeyen/eksik değer 'auto' okunur.
 * - who_am_i isteği articleId ve selectedText TAŞIMAZ (çağıran verse bile atılır).
 * - who_am_i ile /agent/research ASLA çağrılmaz: plan reddedilir, istek gönderilmez.
 * - Çalışma tercihi (modePreference) konudan bağımsızdır ve aynen taşınır.
 */

import type {
  AgentConversationTopic,
  AgentMessageRequest,
  AgentModePreference,
  AgentResearchRequest,
} from '@/types/agent';

export const AGENT_TOPICS: readonly AgentConversationTopic[] = ['auto', 'who_am_i'];

/** Toleranslı konu okuma: yalnız tam 'who_am_i' who_am_i'dir; diğer her şey 'auto'. */
export function normalizeTopic(value: unknown): AgentConversationTopic {
  return value === 'who_am_i' ? 'who_am_i' : 'auto';
}

/** Konu makale bağlamı (articleId/selectedText) kabul eder mi? */
export function topicAllowsArticleContext(topic: AgentConversationTopic): boolean {
  return topic === 'auto';
}

/** Konu ayrı "Derin araştırma" (/agent/research) uç noktasını kullanabilir mi? */
export function topicAllowsResearch(topic: AgentConversationTopic): boolean {
  return topic === 'auto';
}

/** Konu canlı generation_delta metnini gösterebilir mi? who_am_i cevabı yalnız
 * kaynak/politika denetimli terminal sonuçtan gelir (backend delta yayınlamaz;
 * istemci de savunma derinliği için göstermez). */
export function topicStreamsLiveAnswer(topic: AgentConversationTopic): boolean {
  return topic !== 'who_am_i';
}

export interface AgentRequestInput {
  topic: AgentConversationTopic;
  question: string;
  language: 'tr' | 'en';
  modePreference: AgentModePreference;
  deepResearch: boolean;
  idempotencyKey: string;
  conversationId?: string;
  /** Makale bağlamı (yalnız auto'da kullanılır; who_am_i'de atılır). */
  articleId?: string;
  selectedText?: string;
  budgetProfile?: string;
}

export type AgentRequestPlan =
  | { ok: true; endpoint: 'messages'; body: AgentMessageRequest }
  | { ok: true; endpoint: 'research'; body: AgentResearchRequest }
  | { ok: false; reason: 'empty_question' | 'research_not_allowed_for_topic' };

/**
 * Gönderim planı kurar. Dönen gövde istemcinin GÖNDERECEĞİ tam gövdedir (ek alan
 * eklenmez). who_am_i: articleId/selectedText yok; deepResearch → reddedilir.
 */
export function buildAgentRequest(input: AgentRequestInput): AgentRequestPlan {
  const question = input.question.trim();
  if (!question) return { ok: false, reason: 'empty_question' };

  const topic = normalizeTopic(input.topic);
  if (input.deepResearch && !topicAllowsResearch(topic)) {
    return { ok: false, reason: 'research_not_allowed_for_topic' };
  }

  const allowArticle = topicAllowsArticleContext(topic);
  const articleId = allowArticle && input.articleId ? input.articleId : undefined;
  const selectedText = allowArticle && input.selectedText ? input.selectedText : undefined;

  const base: AgentResearchRequest = {
    question,
    language: input.language,
    budgetProfile: input.budgetProfile ?? 'standard',
    conversationTopic: topic,
    conversationId: input.conversationId,
    idempotencyKey: input.idempotencyKey,
  };
  if (articleId) base.articleId = articleId;
  if (selectedText) base.selectedText = selectedText;

  if (input.deepResearch) {
    return { ok: true, endpoint: 'research', body: base };
  }
  return { ok: true, endpoint: 'messages', body: { ...base, modePreference: input.modePreference } };
}
