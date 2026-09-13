import type { DistrictDetail, DistrictSummary, HistoryPoint } from '@/types/district';

// Expo inlines EXPO_PUBLIC_* env vars at build time (no extra config needed).
// Default assumes the backend is reachable at localhost, which only works
// for web / iOS simulator. Android emulator needs http://10.0.2.2:8000, and
// a physical device needs your machine's LAN IP — set EXPO_PUBLIC_API_URL in
// frontend/.env for either case. See frontend/README.md.
const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`);
  } catch (e) {
    throw new ApiError(0, `Could not reach the backend at ${API_BASE_URL} — is it running? (${e})`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail ?? `Request to ${path} failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listDistricts: () => request<DistrictSummary[]>('/districts'),
  getDistrict: (id: string) => request<DistrictDetail>(`/districts/${id}`),
  getDistrictHistory: (id: string, days = 30) =>
    request<HistoryPoint[]>(`/districts/${id}/history?days=${days}`),
};
