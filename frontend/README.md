# Code Fixer — frontend

Local dashboard for the Code Fixer agent: live jobs, and LLM providers & keys. The design is in [docs/frontend.md](../docs/frontend.md).

Built with Next.js 16 (App Router), Tailwind CSS 4 and shadcn/ui (Base UI components).

## Run

```bash
npm install
npm run dev
```

Open http://localhost:3000 for the home page; the dashboard is at `/jobs`.

## Mock vs live data

v0 runs entirely on an **in-browser mock backend** (`src/lib/api/mock-backend.ts`). It simulates a running job moving through the pipeline, request usage and provider recovery, and emits the same events the real SSE stream will.

To use the real FastAPI backend instead, once it exists (roadmap phase 02):

```bash
NEXT_PUBLIC_API_MODE=live BACKEND_URL=http://127.0.0.1:8000 npm run dev
```

`/api/*` is proxied to the backend by `next.config.ts`, so the browser only ever talks to one origin.

## Layout

```
src/
  app/page.tsx         Home page
  app/(dashboard)/     Dashboard layout (sidebar) + jobs/ and providers/ pages
  components/ui/       shadcn/ui components + StatusPill
  components/home/     home sections, animated agent-run card, Reveal / CountUp
  components/layout/   sidebar, header, theme toggle, view-transition wrappers
  components/jobs/     stat cards, jobs table, expandable details, phase timeline
  components/providers/ provider cards, add / rotate / remove dialogs, GitHub card
  hooks/               useAppState (shared store), useNow (shared clock)
  lib/api/             typed API client + mock backend
  lib/sse/             live event stream
  lib/store.ts         client store kept current by events and mutations
  types/               shared types (mirror the backend models)
```

## Notes

- **Keys are write-only.** Key fields are password inputs that are cleared after every submit, and the API only ever returns masked hints.
- **Theme:** an inline script in `<head>` applies light or dark before first paint, following the Next.js 16 "preventing flash before hydration" guide, so `next-themes` isn't needed.
- **Transitions:** route changes use React's `<ViewTransition>` (see `components/layout/transitions.tsx` and the end of `globals.css`). Only one mounted element may carry a given transition name.
- **Prerendering:** both pages prerender as static shells. Anything time-based or random runs only on the client, as Cache Components requires.
