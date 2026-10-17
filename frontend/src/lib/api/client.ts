// Typed client for the backend API (docs/frontend.md §6.1).
// v0 runs against the in-browser mock. Set NEXT_PUBLIC_API_MODE=live to call
// the FastAPI backend through the /api proxy in next.config.ts.

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

export const API_MODE = process.env.NEXT_PUBLIC_API_MODE === "live" ? "live" : "mock";

export interface NewProvider {
  preset: PresetId;
  label?: string;
  apiKey?: string;
  baseUrl?: string;
  models?: ModelRoles;
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.detail ?? `Request failed (${res.status})`);
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
