/** Typed client for the Guardian REST API. */

export interface SessionInfo {
  authenticated: boolean
  login_enabled: boolean
  username: string | null
  expires_at: string | null
}

export interface Overview {
  enabled: boolean
  policy_revision: number
  channel_count: number
  group_count: number
  health_counts: Record<string, number>
  last_run: RunSummary | null
}

export interface RunSummary {
  run_id: string
  dry_run: boolean
  status: string
  result: Record<string, unknown> | null
  error_code: string | null
  error_message: string | null
  started_at: string
  finished_at: string | null
}

export interface Channel {
  channel_id: string
  name: string
  group_id: string | null
  upstream_status: string
  upstream_schedulable: boolean
  health: string
  score: number
  confidence: number
  latency_ms: number | null
  desired_schedulable: boolean
  manual_control: string
  freshness_state: string
  details: Record<string, unknown>
  last_evidence_at: string | null
}

export interface GroupAccount {
  account_id: string
  group_ids: string[]
  status: string
  schedulable: boolean
  expired: boolean
  temporary_unavailable: boolean
  automatic_pause: boolean
  observed_at: string | null
}

export interface Group {
  group_id: string
  name: string
  health: string
  score: number
  channel_count: number
  available_count: number
  latency_ms: number | null
  /** True when the operator excluded this group from Guardian's scope. */
  excluded: boolean
  account_count: number
  accounts: GroupAccount[]
  details: Record<string, unknown>
}

export interface GuardianEvent {
  event_id: string
  event_type: string
  severity: string
  channel_id: string | null
  group_id: string | null
  message: string
  details: Record<string, unknown>
  created_at: string
}

export interface Policy {
  revision: number
  enabled: boolean
  [key: string]: unknown
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/guardian/v1${path}`, {
    // The console authenticates with an HttpOnly cookie.
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  const text = await response.text()
  let payload: unknown = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    payload = null
  }
  if (!response.ok) {
    const body = payload as { error?: { code?: string; message?: string } } | null
    throw new ApiError(
      body?.error?.message ?? `请求失败（HTTP ${response.status}）`,
      response.status,
      body?.error?.code ?? 'UNKNOWN',
    )
  }
  const envelope = payload as { data?: T } | null
  return (envelope?.data ?? (payload as T)) as T
}

export const api = {
  session: () => request<SessionInfo>('/session'),

  login: (username: string, password: string) =>
    request<{ authenticated: boolean; username: string; expires_at: string }>('/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  logout: () => request<{ authenticated: boolean }>('/logout', { method: 'POST' }),

  overview: () => request<Overview>('/overview'),

  status: () => request<Record<string, unknown>>('/status'),

  policy: () => request<Policy>('/policy'),

  updatePolicy: (body: Record<string, unknown>, expectedRevision: number) =>
    request<Policy>('/policy', {
      method: 'PATCH',
      body: JSON.stringify({ ...body, expected_revision: expectedRevision }),
    }),

  channels: (groupId?: string) =>
    request<{ items: Channel[]; next_cursor: string | null }>(
      groupId ? `/channels?group_id=${encodeURIComponent(groupId)}` : '/channels',
    ),

  channel: (id: string) => request<Channel>(`/channels/${id}`),

  groups: () => request<{ items: Group[] }>('/groups'),

  events: (limit = 50) => request<{ items: GuardianEvent[]; next_cursor: string | null }>(`/events?limit=${limit}`),

  probeSpend: () => request<Record<string, unknown>>('/probe-spend'),

  samplingStatus: () => request<Record<string, unknown>>('/sampling/status'),

  recoveryStatus: () => request<Record<string, unknown>>('/recovery/status'),

  startScheduling: (confirm: boolean, idempotencyKey: string) =>
    request<unknown>('/scheduling/start', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ confirm }),
    }),

  stopScheduling: (confirm: boolean, idempotencyKey: string) =>
    request<unknown>('/scheduling/stop', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ confirm }),
    }),
}
