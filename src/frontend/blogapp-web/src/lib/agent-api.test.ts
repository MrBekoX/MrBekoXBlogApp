import axios, { type AxiosInstance } from 'axios';
import { describe, expect, it, vi } from 'vitest';

const transport = vi.hoisted(() => ({ client: null as AxiosInstance | null }));
vi.mock('@/lib/api', () => ({
  apiClient: { post: (...args: Parameters<AxiosInstance['post']>) => transport.client!.post(...args),
    get: (...args: Parameters<AxiosInstance['get']>) => transport.client!.get(...args) },
  getErrorMessage: () => 'Test request failed',
}));
import { agentApi } from './agent-api';

describe('agent API prefix composition', () => {
  it.each(['/api/v1', 'https://api.example/api/v1'])('uses one API prefix with %s', async (baseURL) => {
    const urls: string[] = [];
    transport.client = axios.create({ baseURL, adapter: async (config) => {
      urls.push(axios.getUri(config));
      return { status: 202, statusText: 'Accepted', config, headers: {},
        data: { success: true, data: { runId: 'run-1' } } };
    } });
    await agentApi.sendMessage({ question: 'Question', language: 'en', modePreference: 'auto',
      budgetProfile: 'standard', idempotencyKey: 'test-only', conversationTopic: 'auto' });
    await agentApi.getRun('run-1');
    expect(urls).toEqual([`${baseURL}/agent/messages`, `${baseURL}/agent/runs/run-1`]);
  });
});
