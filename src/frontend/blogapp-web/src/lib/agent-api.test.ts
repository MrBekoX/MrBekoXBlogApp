import { beforeEach, describe, expect, it, vi } from 'vitest';

const post = vi.fn();
const get = vi.fn();

vi.mock('@/lib/api', () => ({
  apiClient: {
    post: (...args: unknown[]) => post(...args),
    get: (...args: unknown[]) => get(...args),
  },
  getErrorMessage: (_error: unknown, fallback: string) => fallback,
}));

const accepted = {
  runId: '11111111-1111-4111-8111-111111111111',
  conversationId: 'c',
  turnSequence: 1,
  acceptedAt: '',
  deadlineAt: '',
  replay: false,
};

describe('agentApi', () => {
  beforeEach(() => {
    post.mockReset();
    get.mockReset();
    post.mockResolvedValue({ data: { success: true, data: accepted } });
    get.mockResolvedValue({ data: { success: true, data: { runId: accepted.runId } } });
  });

  it('who_am_i ile /research ağ isteği yapılmadan reddedilir', async () => {
    const { agentApi, AgentTopicNotAllowedError } = await import('./agent-api');
    await expect(
      agentApi.startResearch({
        question: 'Berkay kimdir?',
        language: 'tr',
        conversationTopic: 'who_am_i',
        idempotencyKey: 'k',
      }),
    ).rejects.toBeInstanceOf(AgentTopicNotAllowedError);
    expect(post).not.toHaveBeenCalled();
  });

  it('auto /research ve who_am_i /messages gövdeyi aynen iletir (conversationTopic dahil)', async () => {
    const { agentApi } = await import('./agent-api');
    await agentApi.startResearch({ question: 'q', language: 'tr', conversationTopic: 'auto', idempotencyKey: 'k1' });
    await agentApi.sendMessage({
      question: 'Hangi üniversitede okudu?',
      language: 'tr',
      modePreference: 'auto',
      conversationTopic: 'who_am_i',
      idempotencyKey: 'k2',
    });
    expect(post.mock.calls[0][0]).toMatch(/\/agent\/research$/);
    expect(post.mock.calls[1][0]).toMatch(/\/agent\/messages$/);
    expect(post.mock.calls[1][1]).toEqual({
      question: 'Hangi üniversitede okudu?',
      language: 'tr',
      modePreference: 'auto',
      conversationTopic: 'who_am_i',
      idempotencyKey: 'k2',
    });
  });

  it('run kimliği yol segmentinde kodlanır', async () => {
    const { agentApi } = await import('./agent-api');
    await agentApi.getRun('../posts?x=1');
    expect(get.mock.calls[0][0]).toMatch(/\/agent\/runs\/\.\.%2Fposts%3Fx%3D1$/);
  });
});
