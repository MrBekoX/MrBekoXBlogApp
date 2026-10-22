import { describe, expect, it } from 'vitest';
import {
  buildAgentRequest,
  normalizeTopic,
  topicAllowsArticleContext,
  topicAllowsResearch,
  topicStreamsLiveAnswer,
  type AgentRequestInput,
} from './topic';

const base: AgentRequestInput = {
  topic: 'auto',
  question: '  Bu yazının ana fikri nedir?  ',
  language: 'tr',
  modePreference: 'analysis',
  deepResearch: false,
  idempotencyKey: 'key-1',
  conversationId: 'conv-1',
  articleId: 'article-1',
  selectedText: 'seçili metin',
};

describe('normalizeTopic', () => {
  it('yalnız tam who_am_i değerini who_am_i okur; diğer her şey auto', () => {
    expect(normalizeTopic('who_am_i')).toBe('who_am_i');
    expect(normalizeTopic('auto')).toBe('auto');
    expect(normalizeTopic(undefined)).toBe('auto');
    expect(normalizeTopic(null)).toBe('auto');
    expect(normalizeTopic('WHO_AM_I')).toBe('auto');
    expect(normalizeTopic('profile')).toBe('auto');
  });

  it('konu yetenekleri: who_am_i makale bağlamı, araştırma ve canlı akış kapalı', () => {
    expect(topicAllowsArticleContext('who_am_i')).toBe(false);
    expect(topicAllowsResearch('who_am_i')).toBe(false);
    expect(topicStreamsLiveAnswer('who_am_i')).toBe(false);
    expect(topicAllowsArticleContext('auto')).toBe(true);
    expect(topicAllowsResearch('auto')).toBe(true);
    expect(topicStreamsLiveAnswer('auto')).toBe(true);
  });
});

describe('buildAgentRequest', () => {
  it('auto: mevcut gövdeyi korur + conversationTopic=auto ekler (messages)', () => {
    const plan = buildAgentRequest(base);
    expect(plan).toEqual({
      ok: true,
      endpoint: 'messages',
      body: {
        question: 'Bu yazının ana fikri nedir?',
        language: 'tr',
        budgetProfile: 'standard',
        conversationTopic: 'auto',
        conversationId: 'conv-1',
        idempotencyKey: 'key-1',
        articleId: 'article-1',
        selectedText: 'seçili metin',
        modePreference: 'analysis',
      },
    });
  });

  it('auto: makale bağlamı kapalıysa articleId göndermez', () => {
    const plan = buildAgentRequest({ ...base, articleId: undefined, selectedText: undefined });
    expect(plan.ok && 'articleId' in plan.body).toBe(false);
  });

  it('auto + derin araştırma: /research, modePreference taşımaz', () => {
    const plan = buildAgentRequest({ ...base, deepResearch: true });
    expect(plan.ok).toBe(true);
    if (!plan.ok) return;
    expect(plan.endpoint).toBe('research');
    expect('modePreference' in plan.body).toBe(false);
    expect(plan.body.conversationTopic).toBe('auto');
    expect(plan.body.articleId).toBe('article-1');
  });

  it('who_am_i: articleId ve selectedText çağıran verse bile ATILIR', () => {
    const plan = buildAgentRequest({ ...base, topic: 'who_am_i' });
    expect(plan.ok).toBe(true);
    if (!plan.ok) return;
    expect(plan.endpoint).toBe('messages');
    expect(plan.body.conversationTopic).toBe('who_am_i');
    expect('articleId' in plan.body).toBe(false);
    expect('selectedText' in plan.body).toBe(false);
    // Tel gövdesinde de yok (JSON serileştirme)
    const wire = JSON.parse(JSON.stringify(plan.body));
    expect(wire.articleId).toBeUndefined();
    expect(wire.selectedText).toBeUndefined();
    // Çalışma tercihi konudan bağımsız korunur
    expect(plan.endpoint === 'messages' && plan.body.modePreference).toBe('analysis');
  });

  it('who_am_i + derin araştırma: /research ASLA planlanmaz (reddedilir)', () => {
    const plan = buildAgentRequest({ ...base, topic: 'who_am_i', deepResearch: true });
    expect(plan).toEqual({ ok: false, reason: 'research_not_allowed_for_topic' });
  });

  it('boş soru reddedilir', () => {
    expect(buildAgentRequest({ ...base, question: '   ' })).toEqual({ ok: false, reason: 'empty_question' });
  });

  it('bilinmeyen konu değeri auto olarak gönderilir (makale bağlamı korunur)', () => {
    const plan = buildAgentRequest({ ...base, topic: 'weird' as never });
    expect(plan.ok && plan.body.conversationTopic).toBe('auto');
  });
});
