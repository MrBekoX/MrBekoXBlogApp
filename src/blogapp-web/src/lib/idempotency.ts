import type { AxiosRequestConfig } from 'axios';

export function createOperationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  return `op_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export function withIdempotencyHeader(
  operationId: string,
  config: AxiosRequestConfig = {}
): AxiosRequestConfig {
  return {
    ...config,
    headers: {
      ...(config.headers ?? {}),
      'Idempotency-Key': operationId,
    },
  };
}
