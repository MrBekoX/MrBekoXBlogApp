import { describe, expect, it } from 'vitest';
import { AGENT_SERVER_LANG, agentTexts, agentTopicTexts } from './agent-i18n';

const NEW_KEYS = [
  'topicLabel',
  'topicAuto',
  'topicWhoAmI',
  'topicHint',
  'topicLockedHint',
  'topicChanged',
  'whoAmITitle',
  'whoAmIAskTitle',
  'whoAmIPanelDescription',
  'whoAmIInputPlaceholder',
  'whoAmIScopeNote',
  'whoAmISuggestionWho',
  'whoAmISuggestionEducation',
  'whoAmISuggestionTeaching',
  'whoAmISuggestionArchitecture',
  'whoAmIStatusStarted',
  'whoAmIVerifiedAnswerNote',
  'whoAmIUnavailable',
  'researchNotAllowed',
  'sourceProfile',
  'sourceProfileSection',
  'sourceUnlinked',
  'unavailableProfileUpdated',
  'unavailableProfileUnavailable',
  'unavailableLegacyProfile',
  'askAgain',
] as const;

describe('agent i18n', () => {
  it('TR ve EN sözlükleri aynı anahtar kümesine sahip ve boş değer yok', () => {
    const trKeys = Object.keys(agentTexts.tr).sort();
    const enKeys = Object.keys(agentTexts.en).sort();
    expect(enKeys).toEqual(trKeys);
    for (const lang of ['tr', 'en'] as const) {
      for (const [key, value] of Object.entries(agentTexts[lang])) {
        expect(typeof value, `${lang}.${key}`).toBe('string');
        expect(value.trim().length, `${lang}.${key}`).toBeGreaterThan(0);
      }
    }
  });

  it('Who am I anahtarları iki dilde de mevcut', () => {
    for (const key of NEW_KEYS) {
      expect(agentTexts.tr[key], `tr.${key}`).toBeTruthy();
      expect(agentTexts.en[key], `en.${key}`).toBeTruthy();
    }
  });

  it('konu sahibi açıkça görünür: "Who am I · Sample Author"', () => {
    expect(agentTexts.tr.topicWhoAmI).toBe('Who am I · Sample Author');
    expect(agentTexts.en.topicWhoAmI).toBe('Who am I · Sample Author');
    expect(agentTexts.tr.whoAmIUnavailable).toContain('Who am I şu an kullanılamıyor');
  });

  it('konu ve çalışma tercihi ayrı etiketlerdir', () => {
    expect(agentTexts.tr.topicLabel).toBe('Konu');
    expect(agentTexts.tr.modeLabel).toBe('Çalışma tercihi');
    expect(agentTexts.tr.topicLabel).not.toBe(agentTexts.tr.modeLabel);
  });

  it('konu metinleri: who_am_i öneri soruları ve makale önerileri ayrı', () => {
    const whoTr = agentTopicTexts('tr', 'who_am_i');
    expect(whoTr.suggestions).toEqual([
      'Sample Author kimdir?',
      'Hangi üniversitede okudu?',
      'Eğitmenlik deneyimi var mı?',
      'Mimari yaklaşımı nedir?',
    ]);
    expect(agentTopicTexts('en', 'who_am_i').suggestions).toHaveLength(4);
    expect(agentTopicTexts('tr', 'auto').suggestions).toEqual([
      agentTexts.tr.suggestionSummary,
      agentTexts.tr.suggestionMainIdea,
      agentTexts.tr.suggestionCode,
    ]);
    expect(whoTr.placeholder).not.toBe(agentTopicTexts('tr', 'auto').placeholder);
    expect(whoTr.title).toBe('Who am I · Sample Author');
  });

  it('sunucu render dili sabit tr (hydration uyumu)', () => {
    expect(AGENT_SERVER_LANG).toBe('tr');
  });
});
