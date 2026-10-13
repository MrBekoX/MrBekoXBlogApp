import { describe, expect, it } from 'vitest';
import type { AgentRunEvent } from '@/types/agent';
import {
  buildAgentSteps,
  deriveEventKind,
  formatDuration,
  isTerminalKind,
  isWaitingInputKind,
  settledStepDurationMs,
  summarizeDetail,
} from './agent-steps-model';

function event(partial: Partial<AgentRunEvent> & { eventSequence: number }): AgentRunEvent {
  return {
    messageType: 'agent.run.progressed',
    messageId: `m-${partial.eventSequence}`,
    occurredAt: '2026-10-13T10:00:00Z',
    ...partial,
  };
}

describe('deriveEventKind', () => {
  it('progressed payload kindını öncelikli kullanır', () => {
    expect(deriveEventKind({ kind: 'retrieval_started', messageType: 'agent.run.progressed' })).toBe('retrieval_started');
  });

  it('terminal messageType son ekinden türetir (noktalı kablo adı)', () => {
    expect(deriveEventKind({ messageType: 'agent.run.completed' })).toBe('completed');
    expect(deriveEventKind({ messageType: 'agent.run.failed' })).toBe('failed');
    expect(deriveEventKind({ messageType: 'agent.run.cancelled' })).toBe('cancelled');
    expect(deriveEventKind({ messageType: 'agent.run.partially_completed' })).toBe('partial');
    expect(deriveEventKind({ messageType: 'agent.action.proposed' })).toBe('action_proposed');
  });

  it('sınıf adı biçimli messageType ile de çalışır (AgentRunCompletedV1)', () => {
    expect(deriveEventKind({ messageType: 'AgentRunCompletedV1' })).toBe('completed');
    expect(deriveEventKind({ messageType: 'AgentRunPartiallyCompletedV1' })).toBe('partial');
    expect(deriveEventKind({ messageType: 'AgentRunFailedV1' })).toBe('failed');
    expect(deriveEventKind({ messageType: 'AgentRunCancelledV1' })).toBe('cancelled');
  });

  it('kind taşımayan progressed olayını genel progress sayar; idari olayları atlar', () => {
    expect(deriveEventKind({ messageType: 'agent.run.progressed' })).toBe('progress');
    expect(deriveEventKind({ messageType: 'agent.run.accepted' })).toBeNull();
  });

  it('agent.run.needs_input B9 bekleme adımıdır; terminal DEĞİLDİR', () => {
    expect(deriveEventKind({ messageType: 'agent.run.needs_input' })).toBe('needs_input');
    expect(deriveEventKind({ messageType: 'AgentRunNeedsInputV1' })).toBe('needs_input');
    expect(isWaitingInputKind('needs_input')).toBe(true);
    expect(isTerminalKind('needs_input')).toBe(false);
  });

  it('progressed tool_error kindı bilinir: araç hatası ayrı adımdır; terminal değildir', () => {
    expect(deriveEventKind({ kind: 'tool_error', messageType: 'agent.run.progressed' })).toBe('tool_error');
    expect(isTerminalKind('tool_error')).toBe(false);
  });

  it('isTerminalKind yalnız terminal türlerini işaretler', () => {
    expect(isTerminalKind('completed')).toBe(true);
    expect(isTerminalKind('partial')).toBe(true);
    expect(isTerminalKind('failed')).toBe(true);
    expect(isTerminalKind('cancelled')).toBe(true);
    expect(isTerminalKind('generation_started')).toBe(false);
    expect(isTerminalKind('progress')).toBe(false);
  });
});

describe('buildAgentSteps', () => {
  it('eşli tamamlama adımına başlangıç zamanını bağlar', () => {
    const steps = buildAgentSteps([
      event({ eventSequence: 1, kind: 'run_started', occurredAt: '2026-10-13T10:00:00Z' }),
      event({ eventSequence: 2, kind: 'retrieval_started', occurredAt: '2026-10-13T10:00:02Z' }),
      event({ eventSequence: 3, kind: 'retrieval_completed', occurredAt: '2026-10-13T10:00:07Z' }),
    ]);

    expect(steps).toHaveLength(3);
    expect(steps[1].kind).toBe('retrieval_started');
    expect(steps[1].startedAt).toBe('2026-10-13T10:00:02Z');
    expect(steps[2].kind).toBe('retrieval_completed');
    expect(steps[2].startedAt).toBe('2026-10-13T10:00:02Z');
    // Eşli adımın sabit süresi: 7s - 2s = 5s
    expect(settledStepDurationMs(steps[2], undefined)).toBe(5000);
  });

  it('kind alanı endpoint henüz eklemediyse olayları ATLAZ, genel adım üretir', () => {
    const steps = buildAgentSteps([
      event({ eventSequence: 1 }),
      event({ eventSequence: 2, messageType: 'agent.run.completed', kind: undefined }),
    ]);
    expect(steps.map((step) => step.kind)).toEqual(['progress', 'completed']);
  });

  it('ikinci araştırma turunu ayrı adım olarak listeler (geliş sırası tek liste)', () => {
    const steps = buildAgentSteps([
      event({ eventSequence: 1, kind: 'research_started', occurredAt: '2026-10-13T10:00:00Z' }),
      event({ eventSequence: 2, kind: 'research_round_completed', occurredAt: '2026-10-13T10:00:05Z' }),
      event({ eventSequence: 3, kind: 'research_round_completed', occurredAt: '2026-10-13T10:00:12Z' }),
    ]);
    expect(steps[1].startedAt).toBe('2026-10-13T10:00:00Z');
    expect(steps[2].startedAt).toBe('2026-10-13T10:00:05Z');
  });

  it('aynı event_sequence tekrar gelirse adım ÇOĞALTMAZ (model düzeyinde idempotent replay)', () => {
    const events = [
      event({ eventSequence: 1, kind: 'generation_started' }),
      event({ eventSequence: 2, kind: 'needs_input' }),
    ];
    // Bileşen imleci olmasa da (doğrudan duplicate liste) sonuç değişmez.
    const steps = buildAgentSteps([...events, ...events]);
    expect(steps.map((step) => step.sequence)).toEqual([1, 2]);
    expect(steps.map((step) => step.kind)).toEqual(['generation_started', 'needs_input']);
  });

  it('geç/stale olayı (son görülenden küçük event_sequence) yok sayar; terminali geri çeviremez', () => {
    const steps = buildAgentSteps([
      event({ eventSequence: 5, kind: 'generation_started' }),
      event({ eventSequence: 3, kind: 'retrieval_started' }), // geç gelen replay
      event({ eventSequence: 6, messageType: 'agent.run.completed' }),
    ]);
    expect(steps.map((step) => step.sequence)).toEqual([5, 6]);
    expect(steps[1].kind).toBe('completed');
  });

  it('kind türetilemeyen duplicate idari olay da imleci ilerletir (çift Accepted tek geçer)', () => {
    const steps = buildAgentSteps([
      event({ eventSequence: 1, messageType: 'agent.run.accepted' }),
      event({ eventSequence: 1, messageType: 'agent.run.accepted' }),
      event({ eventSequence: 2, kind: 'run_started' }),
    ]);
    expect(steps.map((step) => step.sequence)).toEqual([2]);
  });
});

describe('yardımcılar', () => {
  it('formatDuration saniye/dakika biçimler', () => {
    expect(formatDuration(5000, 'tr')).toBe('5 sn');
    expect(formatDuration(65000, 'tr')).toBe('1 dk 05 sn');
    expect(formatDuration(65000, 'en')).toBe('1 m 05 s');
  });

  it('summarizeDetail kısaltır ve anahtarları insanlaştırır', () => {
    const lines = summarizeDetail({
      query_used: '_SIGNALR arama', // değer küratörlü düz metindir
      long_field: 'x'.repeat(200),
      empty: '',
    });
    expect(lines).toHaveLength(2); // boş değer elenir
    expect(lines[0].key).toBe('query used');
    expect(lines[1].value.length).toBeLessThanOrEqual(140);
  });

  it('settledStepDurationMs sonraki adım yoksa null döner (canlı elapsed alanına bırakır)', () => {
    const last = buildAgentSteps([event({ eventSequence: 9, kind: 'generation_started' })]);
    expect(settledStepDurationMs(last[0], undefined)).toBeNull();
  });
});
