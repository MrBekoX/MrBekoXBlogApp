'use client';

/**
 * Agent uç nokta istemcisi (B10). Plan kuralı: tarayıcı Python'a doğrudan istek
 * GÖNDERMEZ; tüm yollar .NET backend outbox/projection hattındadır:
 *   POST /api/v1/agent/messages            → 202 + run_id (kabul)
 *   POST /api/v1/agent/research            → 202 (deep_research sabit mod)
 *   GET  /api/v1/agent/runs/{runId}        → durum + izin verilen sonuç
 *   GET  /api/v1/agent/runs/{runId}/events → yetkili replay (JSON; ?after= imleci)
 *   POST /api/v1/agent/runs/{runId}/cancel → iptal isteniyor kabul durumu
 *   POST /api/v1/agent/runs/{runId}/resume → beklenen input/proposal sürümüyle devam
 *   POST /api/v1/agent/feedback            → run sahipliğiyle geri bildirim
 * Kimlik: mevcut JWT + sunucu tarafı misafir çerezi (withCredentials); istemci
 * owner alanı göndermez — sahiplik kaynağı backend'dir.
 */

import { apiClient } from '@/lib/api';
import { getErrorMessage } from '@/lib/api';
import { API_BASE_URL } from '@/lib/env.client';
import type {
  AgentFeedbackResult,
  AgentMessageRequest,
  AgentRunAccepted,
  AgentRunCancel,
  AgentRunEvents,
  AgentRunResume,
  AgentRunStatus,
} from '@/types/agent';

interface ApiResponse<T> {
  success: boolean;
  data?: T;
  message?: string;
  errors?: string[];
}

// apiClient.baseURL zaten "<origin>/api/v1" olduğu için göreli "/api/v1/agent"
// kullanılırsa yol ikiye katlanır (…/api/v1/api/v1/agent → 404). Base'i
// env.client'tan türet: "<origin>/api/v1/agent" (hub URL'leriyle aynı desen).
const BASE = `${API_BASE_URL}/agent`;

function extractError(error: unknown, fallback: string): string {
  return getErrorMessage(error, fallback);
}

export const agentApi = {
  /** Soru kabulü; 202 Accepted döner (202 axios tarafından başarı sayılır). */
  sendMessage: async (request: AgentMessageRequest): Promise<AgentRunAccepted> => {
    const response = await apiClient.post<ApiResponse<AgentRunAccepted>>(
      `${BASE}/messages`,
      request,
    );
    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.errors?.[0] ?? 'İş kabul edilmedi');
    }
    return response.data.data;
  },

  /** Açık derin araştırma; aynı kabul hattı, mod deep_research (backend sabitler). */
  startResearch: async (
    request: Omit<AgentMessageRequest, 'modePreference'>,
  ): Promise<AgentRunAccepted> => {
    const response = await apiClient.post<ApiResponse<AgentRunAccepted>>(
      `${BASE}/research`,
      request,
    );
    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.errors?.[0] ?? 'Araştırma kabul edilmedi');
    }
    return response.data.data;
  },

  getRun: async (runId: string): Promise<AgentRunStatus> => {
    const response = await apiClient.get<ApiResponse<AgentRunStatus>>(
      `${BASE}/runs/${runId}`,
    );
    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.errors?.[0] ?? 'İş bulunamadı');
    }
    return response.data.data;
  },

  /** Commit edilmiş projection'dan replay; ``after`` ile kaldığı yerden sürer. */
  getEvents: async (runId: string, after = 0, limit = 200): Promise<AgentRunEvents> => {
    const response = await apiClient.get<ApiResponse<AgentRunEvents>>(
      `${BASE}/runs/${runId}/events`,
      { params: { after, limit } },
    );
    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.errors?.[0] ?? 'Olay akışı okunamadı');
    }
    return response.data.data;
  },

  /** İptal TALEBİ: "requested" terminal değildir; terminal cancelled olayı gelir. */
  cancelRun: async (runId: string, reason?: string): Promise<AgentRunCancel> => {
    const response = await apiClient.post<ApiResponse<AgentRunCancel>>(
      `${BASE}/runs/${runId}/cancel`,
      reason ? { reason } : {},
    );
    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.errors?.[0] ?? 'İptal isteği kaydedilemedi');
    }
    return response.data.data;
  },

  /** B9 sözleşmesi: beklenen input/proposal sürümü doğrulanarak devam isteği. */
  resumeRun: async (
    runId: string,
    versions: { expectedInputVersion?: number; expectedProposalVersion?: number },
  ): Promise<AgentRunResume> => {
    const response = await apiClient.post<ApiResponse<AgentRunResume>>(
      `${BASE}/runs/${runId}/resume`,
      versions,
    );
    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.errors?.[0] ?? 'Devam isteği kaydedilemedi');
    }
    return response.data.data;
  },

  /** Run sahipliğiyle idempotent geri bildirim; feedbackKey tek kullanımlık anahtar. */
  sendFeedback: async (
    runId: string,
    rating: number,
    feedbackKey: string,
    comment?: string,
  ): Promise<AgentFeedbackResult> => {
    const response = await apiClient.post<ApiResponse<AgentFeedbackResult>>(
      `${BASE}/feedback`,
      { runId, rating, comment, feedbackKey },
    );
    if (!response.data.success || !response.data.data) {
      throw new Error(response.data.errors?.[0] ?? 'Geri bildirim kaydedilemedi');
    }
    return response.data.data;
  },
};

export { extractError as agentErrorMessage };
