import { AxiosError } from 'axios';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { withIdempotencyHeader } from '../idempotency';
import { apiClient, authApi, createAuthMutationConfig, postsApi } from '../api';

describe('idempotency header helper', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('preserves existing request configuration while injecting the header', () => {
    const config = withIdempotencyHeader('op-123', {
      params: { retry: true },
      headers: {
        Authorization: 'Bearer token',
      },
    });

    expect(config.params).toEqual({ retry: true });
    expect(config.headers).toMatchObject({
      Authorization: 'Bearer token',
      'Idempotency-Key': 'op-123',
    });
  });

  it('creates auth mutation config with a stable Idempotency-Key', () => {
    const { operationId, config } = createAuthMutationConfig('auth-op-1');

    expect(operationId).toBe('auth-op-1');
    expect(config.headers).toMatchObject({
      'Idempotency-Key': 'auth-op-1',
    });
  });

  it('attaches Idempotency-Key to login requests', async () => {
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { success: true },
    });

    await authApi.login({ email: 'admin@example.com', password: 'secret' }, 'login-op-1');

    expect(postSpy).toHaveBeenCalledWith(
      '/auth/login',
      { email: 'admin@example.com', password: 'secret' },
      expect.objectContaining({
        headers: expect.objectContaining({
          'Idempotency-Key': 'login-op-1',
        }),
      }),
    );
  });

  it('attaches Idempotency-Key to refresh token requests', async () => {
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { success: true },
    });

    await authApi.refreshToken('refresh-op-1');

    expect(postSpy).toHaveBeenCalledWith(
      '/auth/refresh-token',
      null,
      expect.objectContaining({
        headers: expect.objectContaining({
          'Idempotency-Key': 'refresh-op-1',
        }),
      }),
    );
  });

  it('reuses a generated Idempotency-Key across auth network retries', async () => {
    const randomUuidSpy = vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('retry-auth-op-1');
    const postSpy = vi.spyOn(apiClient, 'post')
      .mockRejectedValueOnce(new AxiosError('Network Error', 'ERR_NETWORK'))
      .mockResolvedValueOnce({
        data: { success: true },
      });

    await authApi.login({ email: 'admin@example.com', password: 'secret' });

    expect(randomUuidSpy).toHaveBeenCalledTimes(1);
    expect(postSpy).toHaveBeenCalledTimes(2);
    expect(postSpy.mock.calls[0]?.[2]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          'Idempotency-Key': 'retry-auth-op-1',
        }),
      }),
    );
    expect(postSpy.mock.calls[1]?.[2]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          'Idempotency-Key': 'retry-auth-op-1',
        }),
      }),
    );
  });

  it('reuses the provided Idempotency-Key across post retries', async () => {
    const postSpy = vi.spyOn(apiClient, 'post')
      .mockRejectedValueOnce(new AxiosError('Network Error', 'ERR_NETWORK'))
      .mockResolvedValueOnce({
        data: { success: true, data: { id: 'post-1' } },
      });

    await postsApi.create({ title: 'Retry title' }, 'retry-post-op-1');

    expect(postSpy).toHaveBeenCalledTimes(2);
    expect(postSpy.mock.calls[0]?.[2]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          'Idempotency-Key': 'retry-post-op-1',
        }),
      }),
    );
    expect(postSpy.mock.calls[1]?.[2]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          'Idempotency-Key': 'retry-post-op-1',
        }),
      }),
    );
  });

  it('uses authApi.refreshToken inside the 401 retry interceptor', async () => {
    const rejected = apiClient.interceptors.response.handlers.find((handler) => typeof handler?.rejected === 'function')?.rejected;
    const refreshSpy = vi.spyOn(authApi, 'refreshToken').mockResolvedValue({ success: true });
    expect(rejected).toBeTypeOf('function');
    const originalAdapter = apiClient.defaults.adapter;
    const adapterSpy = vi.fn().mockResolvedValue({
      data: { success: true },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: {},
    });
    apiClient.defaults.adapter = adapterSpy;

    try {
      const result = await rejected({
        response: { status: 401 },
        config: {
          url: '/posts',
          method: 'get',
          headers: {},
        },
      });

      expect(refreshSpy).toHaveBeenCalledTimes(1);
      expect(adapterSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          url: '/posts',
          _retry: true,
        }),
      );
      expect(result).toMatchObject({
        data: { success: true },
        status: 200,
      });
    } finally {
      apiClient.defaults.adapter = originalAdapter;
    }
  });
});
