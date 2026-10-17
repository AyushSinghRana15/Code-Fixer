// Typed client for the backend API (docs/frontend.md §6.1).
// Talks to the FastAPI backend (`uv run fixer serve`) through the /api proxy in next.config.ts.
// Set NEXT_PUBLIC_API_MODE=mock to use the in-browser mock instead (no backend needed).

import { ApiError, getMockBackend } from "@/lib/api/mock-backend";
import type {
  GithubCredential,
  Job,
  ModelRoles,
  PresetId,
  Provider,
  ProviderTestResult,
  StatsSummary,
} from "@/types";

export { ApiError };

export const API_MODE = process.env.NEXT_PUBLIC_API_MODE === "mock" ? "mock" : "live";

export const BACKEND_DOWN =
  "Can't reach the Code Fixer API. Start it with: cd backend && uv run fixer serve";

export interface NewProvider {
  preset: PresetId;
  label?: string;
  apiKey?: string;
  baseUrl?: string;
  models?: ModelRoles;
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(BACKEND_DOWN);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    // the Next.js proxy answers 500 with an HTML page when the backend isn't running
    throw new ApiError(body?.detail ?? (res.status >= 500 ? BACKEND_DOWN : `Request failed (${res.status})`));
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});

const live = {
  listJobs: () => http<Job[]>("/jobs?limit=50"),
  getStats: () => http<StatsSummary>("/stats/summary"),
  listProviders: () => http<Provider[]>("/providers"),
  addProvider: (p: NewProvider) => http<Provider[]>("/providers", json("POST", p)),
  setEnabled: (id: string, enabled: boolean) =>
    http<Provider[]>(`/providers/${id}`, json("PATCH", { enabled })),
  reorder: (ids: string[]) => http<Provider[]>("/providers/order", json("PUT", ids)),
  testProvider: (id: string) => http<ProviderTestResult>(`/providers/${id}/test`, json("POST")),
  rotateKey: (id: string, apiKey: string) =>
    http<Provider[]>(`/providers/${id}/key`, json("PUT", { apiKey })),
  removeProvider: (id: string) => http<Provider[]>(`/providers/${id}`, json("DELETE")),
  getGithub: () => http<GithubCredential>("/credentials/github"),
  setGithubToken: (token: string) =>
    http<GithubCredential>("/credentials/github", json("PUT", { token })),
  testGithub: () => http<GithubCredential>("/credentials/github/test", json("POST")),
  removeGithub: () => http<GithubCredential>("/credentials/github", json("DELETE")),
};

type Api = typeof live;

const mock: Api = {
  listJobs: () => getMockBackend().listJobs(),
  getStats: () => getMockBackend().getStats(),
  listProviders: () => getMockBackend().listProviders(),
  addProvider: (p) => getMockBackend().addProvider(p),
  setEnabled: (id, enabled) => getMockBackend().setEnabled(id, enabled),
  reorder: (ids) => getMockBackend().reorder(ids),
  testProvider: (id) => getMockBackend().testProvider(id),
  rotateKey: (id, apiKey) => getMockBackend().rotateKey(id, apiKey),
  removeProvider: (id) => getMockBackend().removeProvider(id),
  getGithub: () => getMockBackend().getGithub(),
  setGithubToken: (token) => getMockBackend().setGithubToken(token),
  testGithub: () => getMockBackend().testGithub(),
  removeGithub: () => getMockBackend().removeGithub(),
};

export const api: Api = API_MODE === "live" ? live : mock;
