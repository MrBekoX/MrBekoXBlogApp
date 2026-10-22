import { AxiosError, AxiosHeaders, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import { describe, expect, it } from 'vitest';
import { agentTexts } from '@/lib/agent-i18n';
import type { AgentPhase, AgentRunEvent } from '@/types/agent';
import {
  isCapabilityUnavailableError,
  liveAnswerFor,
  mergePhase,
  phaseFromStatus,
  shouldIngestNotification,
  submitErrorKind,
  unavailableMessage,
  validateRestoredRun,
} from './session-model';

const RUN = '11111111-1111-4111-8111-111111111111';
const ARTICLE = 'aaaaaaaa-0000-4000-8000-000000000001';

function httpError(status: number, data: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
  const response = { status, statusText: '', headers: {}, config, data } as AxiosResponse;
  return new AxiosError('request failed', 'ERR_BAD_RESPONSE', config, undefined, response);
}

describe('phaseFromStatus / mergePhase', () => {
  it('backend durumlarını faz makinesine çevirir (eski panel eşlemesi)', () => {
    expect(phaseFromStatus({ status: 'Completed' })).toBe('completed');
    expect(phaseFromStatus({ status: 'PartiallyCompleted' })).toBe('partial');
    expect(phaseFromStatus({ status: 'Failed' })).toBe('failed');
    expect(phaseFromStatus({ status: 'Cancelled' })).toBe('cancelled');
    expect(phaseFromStatus({ status: 'Accepted', selectedMode: null })).toBe('starting');
    expect(phaseFromStatus({ status: 'Accepted', selectedMode: 'fast' })).toBe('started');
  });

  it('"iptal isteniyor" terminal değildir ve geç gelen started ile silinmez', () => {
    expect(mergePhase('cancelling', 'started')).toBe('cancelling');
    expect(mergePhase('cancelling', 'starting')).toBe('cancelling');
    expect(mergePhase('cancelling', 'cancelled')).toBe('cancelled');
  });

  it('terminal faz geç replay/durumla geri çevrilemez; terminal güncellemesi kazanır', () => {
    const terminals: AgentPhase[] = ['completed', 'partial', 'failed', 'cancelled'];
    for (const terminal of terminals) {
      expect(mergePhase(terminal, 'started')).toBe(terminal);
      expect(mergePhase(terminal, 'cancelling')).toBe(terminal);
    }
    expect(mergePhase('completed', 'partial')).toBe('partial');
  });

  it('aktif fazlar ileri gider, geri gitmez', () => {
    expect(mergePhase('accepted', 'started')).toBe('started');
    expect(mergePhase('started', 'starting')).toBe('started');
    expect(mergePhase('starting', 'cancelling')).toBe('cancelling');
  });
});

describe('validateRestoredRun (konu/run/sahip sızıntısı yok)', () => {
  const autoArticleRun = { runId: RUN, conversationTopic: 'auto', articleId: ARTICLE };

  it('makale paneli: aynı konu + aynı makale geçer (GUID büyük/küçük harf toleranslı)', () => {
    expect(validateRestoredRun(autoArticleRun, RUN, { topic: 'auto', articleId: ARTICLE }).ok).toBe(true);
    expect(
      validateRestoredRun({ ...autoArticleRun, articleId: ARTICLE.toUpperCase() }, RUN, {
        topic: 'auto',
        articleId: ARTICLE,
      }).ok,
    ).toBe(true);
  });

  it('makale bağlamı kapalı auto run (articleId yok) aynı panelde geçer', () => {
    expect(
      validateRestoredRun({ runId: RUN, conversationTopic: 'auto', articleId: null }, RUN, {
        topic: 'auto',
        articleId: ARTICLE,
      }).ok,
    ).toBe(true);
  });

  it('eski backend konu alanı göndermezse auto sayılır', () => {
    expect(validateRestoredRun({ runId: RUN, articleId: ARTICLE }, RUN, { topic: 'auto', articleId: ARTICLE }).ok).toBe(
      true,
    );
    expect(validateRestoredRun({ runId: RUN }, RUN, { topic: 'who_am_i' })).toEqual({
      ok: false,
      reason: 'topic_mismatch',
    });
  });

  it('konu uyuşmazlığı reddedilir (auto run who_am_i paneline, who_am_i run auto paneline yüklenmez)', () => {
    expect(validateRestoredRun(autoArticleRun, RUN, { topic: 'who_am_i' })).toEqual({
      ok: false,
      reason: 'topic_mismatch',
    });
    expect(
      validateRestoredRun({ runId: RUN, conversationTopic: 'who_am_i', articleId: null }, RUN, {
        topic: 'auto',
        articleId: ARTICLE,
      }),
    ).toEqual({ ok: false, reason: 'topic_mismatch' });
  });

  it('başka makalenin run kaydı reddedilir', () => {
    expect(validateRestoredRun(autoArticleRun, RUN, { topic: 'auto', articleId: 'other-article' })).toEqual({
      ok: false,
      reason: 'article_mismatch',
    });
  });

  it('who_am_i: makaleye bağlı run reddedilir; makalesiz run geçer', () => {
    expect(
      validateRestoredRun({ runId: RUN, conversationTopic: 'who_am_i', articleId: ARTICLE }, RUN, {
        topic: 'who_am_i',
      }),
    ).toEqual({ ok: false, reason: 'article_mismatch' });
    expect(
      validateRestoredRun({ runId: RUN, conversationTopic: 'who_am_i', articleId: null }, RUN, { topic: 'who_am_i' })
        .ok,
    ).toBe(true);
  });

  it('backend farklı run kimliği döndürürse reddedilir', () => {
    expect(
      validateRestoredRun({ ...autoArticleRun, runId: '22222222-2222-4222-8222-222222222222' }, RUN, {
        topic: 'auto',
        articleId: ARTICLE,
      }),
    ).toEqual({ ok: false, reason: 'run_mismatch' });
  });
});

describe('shouldIngestNotification', () => {
  it('başka run ve imleçten geride kalan bildirim yok sayılır', () => {
    expect(shouldIngestNotification({ run_id: 'other', event_sequence: 9 }, RUN, 3)).toBe(false);
    expect(shouldIngestNotification({ run_id: RUN, event_sequence: 3 }, RUN, 3)).toBe(false);
    expect(shouldIngestNotification({ run_id: RUN, event_sequence: 2 }, RUN, 3)).toBe(false);
    expect(shouldIngestNotification({ run_id: RUN, event_sequence: 4 }, RUN, 3)).toBe(true);
    expect(shouldIngestNotification(null, RUN, 0)).toBe(false);
  });
});

describe('liveAnswerFor', () => {
  const events: AgentRunEvent[] = [
    { eventSequence: 1, messageType: 'agent.run.progressed', messageId: 'a', occurredAt: '', kind: 'generation_delta', message: 'Mer' },
    { eventSequence: 2, messageType: 'agent.run.progressed', messageId: 'b', occurredAt: '', kind: 'generation_delta', message: 'haba' },
  ];

  it('akışa açık konuda delta metnini birleştirir', () => {
    expect(liveAnswerFor(events, true)).toBe('Merhaba');
  });

  it('who_am_i (akış kapalı): delta gelse bile metin gösterilmez', () => {
    expect(liveAnswerFor(events, false)).toBe('');
  });
});

describe('unavailableMessage', () => {
  const tr = agentTexts.tr;
  const en = agentTexts.en;

  it.each([
    ['profile_updated', 'unavailableProfileUpdated'],
    ['profile_unavailable', 'unavailableProfileUnavailable'],
    ['legacy_profile_unavailable', 'unavailableLegacyProfile'],
  ] as const)('%s → yerelleştirilmiş mesaj + yeniden sor önerisi', (code, key) => {
    expect(unavailableMessage(code, tr)).toEqual({ message: tr[key], askAgain: true });
    expect(unavailableMessage(` ${code.toUpperCase()} `, en)).toEqual({ message: en[key], askAgain: true });
  });

  it('makale guard gerekçesi önek tekrarlanmadan gösterilir', () => {
    const reason = 'İçerik kullanılamıyor: sonucun dayandığı makale güncel yayın erişimini kaybetti.';
    expect(unavailableMessage(reason, tr)).toEqual({ message: reason, askAgain: false });
  });

  it('bilinmeyen gerekçe eski biçimle gösterilir', () => {
    expect(unavailableMessage('article_unpublished', en)).toEqual({
      message: 'Content unavailable: article_unpublished',
      askAgain: false,
    });
  });
});

describe('submitErrorKind (who_am_i kapasite hatası)', () => {
  it('who_am_i + 503 → capability_unavailable (normal sohbete düşüş yok)', () => {
    expect(submitErrorKind(httpError(503, { success: false, errors: ['Servis kullanılamıyor'] }), 'who_am_i')).toBe(
      'capability_unavailable',
    );
  });

  it('who_am_i + açık capability_unavailable kodu (alan adı toleranslı)', () => {
    expect(submitErrorKind(httpError(400, { success: false, code: 'capability_unavailable' }), 'who_am_i')).toBe(
      'capability_unavailable',
    );
    expect(isCapabilityUnavailableError(httpError(503, { errors: ['capability_unavailable'] }))).toBe(true);
    expect(isCapabilityUnavailableError(httpError(503, { errorCode: 'CAPABILITY_UNAVAILABLE' }))).toBe(true);
  });

  it('who_am_i + validation 400 genel hata yolunu kullanır', () => {
    expect(submitErrorKind(httpError(400, { success: false, errors: ['konu değişti'] }), 'who_am_i')).toBe('other');
  });

  it('auto konusunda 503 mevcut genel hata yolunu korur', () => {
    expect(submitErrorKind(httpError(503, { code: 'capability_unavailable' }), 'auto')).toBe('other');
  });

  it('axios dışı hata other', () => {
    expect(submitErrorKind(new Error('boom'), 'who_am_i')).toBe('other');
  });
});
