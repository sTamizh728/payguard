// The phone reaches the backend through `adb reverse tcp:8000 tcp:8000`.
export const BACKEND_URL = 'http://127.0.0.1:8000';

export class LoginExpired extends Error {}

export type PendingAction = {
  id: string;
  type: 'payout' | 'refund' | string;
  summary: string;
  // Scam guard: warning signs and the cooling-off wait before Confirm works.
  warnings?: string[];
  wait_seconds?: number;
};

export type AssistantReply = {
  reply: string;
  pending_action: PendingAction | null;
  transactions: Record<string, any>[];
  event: string | null;
};

export const api = async <T = any>(
  path: string,
  token: string | null,
  options: {method?: string; body?: object} = {},
): Promise<T> => {
  const response = await fetch(`${BACKEND_URL}${path}`, {
    method: options.method ?? (options.body ? 'POST' : 'GET'),
    headers: {
      'Content-Type': 'application/json',
      ...(token ? {Authorization: `Bearer ${token}`} : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  if (response.status === 401 && token) {
    throw new LoginExpired('Your login has expired. Please log in again.');
  }

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      typeof data.detail === 'string'
        ? data.detail
        : 'PayGuard could not reach the server. Please try again.',
    );
  }

  return data as T;
};
