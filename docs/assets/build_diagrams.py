"""Generate the animated diagrams used in README.md.

Run:  python3 docs/assets/build_diagrams.py
Writes, next to this file:
  build-roadmap-{light,dark}.svg   engineering phases (milestones)   -> ROADMAP
  harness-ladder-{light,dark}.svg  the agent's runtime pipeline      -> PHASES / LOOPS
  project-layout-{light,dark}.svg  repo folder map                   -> LAYOUT_*

Progress tracking: when a milestone is reached, update ROADMAP_MILESTONE and the
ROADMAP statuses ("planned" | "next" | "building" | "done"). When a runtime phase
gets implemented, update its status in PHASES. Then re-run this script.
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent

# ---- Build roadmap: engineering phases, bottom rung first (see Plan.md §12) ----
ROADMAP_MILESTONE = "Next: 02 · Backend"
ROADMAP = [
    ("Frontend", "Next.js dashboard: jobs, providers & keys", "done"),
    ("Backend", "FastAPI, live events, encrypted key vault", "next"),
    ("Orchestration", "Agent pipeline, free-LLM router, tools, Docker sandbox", "planned"),
    ("Memory & Retrieval", "Code search, repo memory", "planned"),
    ("Observability", "Traces, logs, metrics", "planned"),
    ("Guardrails", "NVIDIA NeMo rails + safety checks", "planned"),
    ("Testing & Evals", "Tests, eval sets, CI", "planned"),
    ("Package & Deploy", "Docker images, pip package, compose", "planned"),
    ("Context Engineering", "Lean, focused agent context", "planned"),
    ("Cost Optimization", "Fewer tokens and requests per fix", "planned"),
]

# ---- Project layout map: (folder, what it holds) ----
LAYOUT_FRONTEND = [
    ("app/jobs/", "Jobs dashboard"), ("app/providers/", "Providers & keys"),
    ("components/", "UI + shadcn/ui"), ("hooks/", "data + live stream"),
    ("lib/", "API + SSE client"), ("types/", "shared types"),
]
# (lane title, theme color key, [(folder, what it holds)])
LAYOUT_BACKEND = [
    ("Interface", "prepare", [("api/", "REST + live events"), ("cli/", "fixer command")]),
    ("Agent core", "understand", [("orchestrator/", "pipeline + budgets"), ("agent/", "loop + prompts"),
                                  ("tools/", "files, search, tests")]),
    ("Models & keys", "next", [("llm/", "router + failover"), ("vault/", "encrypted keys")]),
    ("Execution", "fix", [("sandbox/", "Docker per job"), ("github/", "PRs + comments")]),
    ("Knowledge", "ship", [("store/", "jobs + logs"), ("memory/", "repo memory + search"),
                           ("observability/", "traces + metrics")]),
    ("Quality", "teal", [("guards/", "NeMo rails + checks"), ("evals/", "benchmarks")]),
]
LAYOUT_OTHER = [
    ("backend/tests/", "unit + integration tests"),
    ("docs/", "plan, frontend design, diagrams"),
    ("deploy/", "Docker, compose, CI"),
]

# ---- Agent runtime pipeline ----
# Header label for the runtime ladder.
MILESTONE = "Agent runtime"

# (title, description, kind, group, status) — listed bottom rung first.
# kind: "code" = plain code, "cheap" = cheap/fast model, "llm" = main model
# status: "planned" | "building" | "done"
PHASES = [
    ("Intake", "Parse issue, stack traces, CI logs into a task spec", "cheap", "prepare", "planned"),
    ("Env setup", "Clone repo, detect stack, build the Docker sandbox", "code", "prepare", "planned"),
    ("Baseline", "Run the full suite before changing anything", "code", "prepare", "planned"),
    ("Reproduce", "Write a test that fails because of the bug", "llm", "understand", "planned"),
    ("Localize", "Stack trace + ripgrep + symbols give suspect files", "code", "understand", "planned"),
    ("Fix loop", "Edit, run targeted tests, read failures, repeat", "llm", "fix", "planned"),
    ("Verify", "Full suite + lint + types, compared with baseline", "code", "fix", "planned"),
    ("Review", "Critic checks the diff; guard blocks test tampering", "llm", "fix", "planned"),
    ("Deliver", "Push branch, open PR with root cause and results", "cheap", "ship", "planned"),
    ("Feedback", "Act on PR review comments and CI results", "llm", "ship", "planned"),
    ("Learn", "Save trajectory, repo memory and eval metrics", "cheap", "ship", "planned"),
]

# (letter, from rung, to rung, bulge width, legend text) — rungs are 1-based
LOOPS = [
    ("A", 7, 6, 46, "Verify → Fix: new test failures"),
    ("B", 8, 6, 92, "Review → Fix: critic or tamper guard rejects"),
    ("C", 10, 6, 140, "Feedback → Fix: review comments or red CI"),
    ("D", 6, 5, 46, "Fix → Localize: stuck on the same failure"),
]

GROUPS = [("prepare", "Prepare"), ("understand", "Understand"), ("fix", "Fix"), ("ship", "Ship")]
KIND_LABEL = {"code": "code", "cheap": "cheap LLM", "llm": "LLM"}
STATUS_LABEL = {"planned": "○ planned", "next": "▶ next", "building": "◐ building", "done": "✓ done"}

THEMES = {
    "light": {
        "bg": "#f6f8fa", "border": "#d0d7de", "card": "#ffffff", "text": "#1f2328",
        "muted": "#59636e", "rail": "#8c959f", "accent": "#bf3989",
        "prepare": "#0969da", "understand": "#8250df", "fix": "#bc4c00", "ship": "#1a7f37",
        "code_bg": "#eaeef2", "code_fg": "#59636e", "cheap_bg": "#ddf4ff", "cheap_fg": "#0969da",
        "llm_bg": "#fbefff", "llm_fg": "#8250df",
        "teal": "#1b7c83",
        "planned": "#8c959f", "next": "#bf3989", "building": "#9a6700", "done": "#1a7f37",
    },
    "dark": {
        "bg": "#161b22", "border": "#30363d", "card": "#0d1117", "text": "#e6edf3",
        "muted": "#9198a1", "rail": "#6e7681", "accent": "#db61a2",
        "prepare": "#4493f8", "understand": "#ab7df8", "fix": "#f0883e", "ship": "#3fb950",
        "code_bg": "#21262d", "code_fg": "#9198a1", "cheap_bg": "#0c2d6b", "cheap_fg": "#79c0ff",
        "llm_bg": "#271052", "llm_fg": "#d2a8ff",
        "teal": "#39c5cf",
        "planned": "#6e7681", "next": "#db61a2", "building": "#d29922", "done": "#3fb950",
    },
}

W, H = 960, 1150
RAIL_L, RAIL_R = 230, 300
MID = (RAIL_L + RAIL_R) / 2
TOP_Y, STEP = 200, 66
CARD_X, CARD_W, CARD_H = 330, 590, 52
DUR = 14  # seconds per climb
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def rung_y(i: int) -> float:
    """y of rung i (1 = bottom)."""
    return TOP_Y + (len(PHASES) - i) * STEP


def loop_path(frm: int, to: int, d: float) -> str:
    x0, y1, y2 = RAIL_L - 4, rung_y(frm), rung_y(to)
    return f"M{x0},{y1} C{x0 - d},{y1} {x0 - d},{y2} {x0},{y2}"


def bezier_len(p0, p1, p2, p3, n=200) -> float:
    pts = []
    for k in range(n + 1):
        t = k / n
        a, b, c, e = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1]))
    return sum(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 for (x1, y1), (x2, y2) in zip(pts, pts[1:]))


def climber():
    """Path the climbing dot follows: up to Verify, around loop A, then to the top.
    Returns (svg path, {rung: [time fractions when the dot reaches it]})."""
    a = next(lp for lp in LOOPS if lp[0] == "A")
    frm, to, d = a[1], a[2], a[3]
    x0 = RAIL_L - 4
    y1, yf, yt, ytop = rung_y(1), rung_y(frm), rung_y(to), rung_y(len(PHASES))
    path = (f"M{MID},{y1} L{MID},{yf} L{x0},{yf} "
            f"C{x0 - d},{yf} {x0 - d},{yt} {x0},{yt} L{MID},{yt} L{MID},{ytop}")
    side = MID - x0
    curve = bezier_len((x0, yf), (x0 - d, yf), (x0 - d, yt), (x0, yt))
    total = (y1 - yf) + side + curve + side + (yt - ytop)

    # distance along the path where the dot passes each rung
    hits = {i: [] for i in range(1, len(PHASES) + 1)}
    for i in range(1, frm + 1):
        hits[i].append(y1 - rung_y(i))
    back = (y1 - yf) + side + curve + side
    for i in range(to, len(PHASES) + 1):
        hits[i].append(back + (yt - rung_y(i)))

    start, end = 0.04, 0.86
    times = {i: [start + (end - start) * s / total for s in v] for i, v in hits.items()}
    return path, times, (start, end)


def glow_anim(hit_times, dur=DUR) -> str:
    pts = [(0.0, 0.0)]
    for n, t in enumerate(sorted(hit_times)):
        pts += [(t - 0.012, 0.0 if n == 0 else 0.3), (t, 1.0), (t + 0.05, 0.3)]
    pts += [(0.97, 0.3), (1.0, 0.0)]
    kt = ";".join(f"{t:.4f}" for t, _ in pts)
    vals = ";".join(f"{v}" for _, v in pts)
    return (f'<animate attributeName="opacity" dur="{dur}s" repeatCount="indefinite" '
            f'calcMode="linear" keyTimes="{kt}" values="{vals}"/>')


def text(x, y, s, size, fill, weight="normal", anchor="start", family=FONT, extra=""):
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}" {extra}>{escape(s)}</text>')


def build(theme: str) -> str:
    c = THEMES[theme]
    path, times, (t0, t1) = climber()
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'role="img" aria-label="Code Fixer harness: an 11-phase ladder from Intake to Learn, '
         f'with loops back to the Fix phase when checks fail">']
    o.append(f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" '
             f'markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{c["fix"]}"/></marker></defs>')
    o.append(f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="14" fill="{c["bg"]}" stroke="{c["border"]}"/>')

    # header
    o.append(text(40, 52, "Code Fixer — harness ladder", 24, c["text"], "700"))
    o.append(text(40, 78, "Each rung must pass before the agent climbs. When a check fails, it loops back down.",
                  14, c["muted"]))

    # build progress (top right)
    done = sum(p[4] == "done" for p in PHASES)
    building = sum(p[4] == "building" for p in PHASES)
    px, pw = W - 300, 260
    o.append(text(px + pw, 40, MILESTONE, 12.5, c["muted"], "600", "end"))
    o.append(text(px, 66, f"Built {done} / {len(PHASES)} phases", 13, c["text"], "700"))
    o.append(f'<rect x="{px}" y="76" width="{pw}" height="8" rx="4" fill="{c["code_bg"]}"/>')
    seg = pw / len(PHASES)
    if done:
        o.append(f'<rect x="{px}" y="76" width="{seg * done}" height="8" rx="4" fill="{c["done"]}"/>')
    if building:
        o.append(f'<rect x="{px + seg * done}" y="76" width="{seg * building}" height="8" rx="4" '
                 f'fill="{c["building"]}"/>')

    # goal flag at the top of the ladder
    ytop = rung_y(len(PHASES))
    o.append(f'<g><rect x="{MID - 88}" y="{ytop - 78}" width="176" height="34" rx="17" '
             f'fill="{c["ship"]}" opacity="0.15"/>'
             f'<rect x="{MID - 88}" y="{ytop - 78}" width="176" height="34" rx="17" fill="none" '
             f'stroke="{c["ship"]}" stroke-width="1.5"/>'
             + text(MID, ytop - 56, "✓ Bug fixed & merged", 14, c["ship"], "700", "middle") +
             f'<rect x="{MID - 88}" y="{ytop - 78}" width="176" height="34" rx="17" fill="{c["ship"]}" opacity="0">'
             f'<animate attributeName="opacity" dur="{DUR}s" repeatCount="indefinite" '
             f'keyTimes="0;{t1 - 0.01:.3f};{t1 + 0.02:.3f};0.97;1" values="0;0;0.35;0.2;0"/></rect></g>')

    # rails
    ybot = rung_y(1)
    for x in (RAIL_L, RAIL_R):
        o.append(f'<line x1="{x}" y1="{ytop - 34}" x2="{x}" y2="{ybot + 34}" stroke="{c["rail"]}" '
                 f'stroke-width="6" stroke-linecap="round"/>')

    # loops (dashed, flowing)
    for letter, frm, to, d, _ in LOOPS:
        o.append(f'<path d="{loop_path(frm, to, d)}" fill="none" stroke="{c["fix"]}" stroke-width="2" '
                 f'stroke-dasharray="6 4" marker-end="url(#arrow)" opacity="0.85">'
                 f'<animate attributeName="stroke-dashoffset" from="20" to="0" dur="1.2s" '
                 f'repeatCount="indefinite"/></path>')
        lx, ly = RAIL_L - 4 - 0.75 * d, (rung_y(frm) + rung_y(to)) / 2
        o.append(f'<circle cx="{lx}" cy="{ly}" r="11" fill="{c["bg"]}" stroke="{c["fix"]}" stroke-width="1.5"/>')
        o.append(text(lx, ly + 4, letter, 11, c["fix"], "700", "middle"))

    # rungs + cards
    for i, (title, desc, kind, group, status) in enumerate(PHASES, start=1):
        y, g = rung_y(i), c[group]
        o.append(f'<line x1="{RAIL_L}" y1="{y}" x2="{RAIL_R}" y2="{y}" stroke="{c["rail"]}" '
                 f'stroke-width="6" stroke-linecap="round"/>')
        o.append(f'<line x1="{RAIL_R}" y1="{y}" x2="{CARD_X}" y2="{y}" stroke="{c["rail"]}" stroke-width="1.5"/>')
        built = status == "done"
        o.append(f'<circle cx="{MID}" cy="{y}" r="14" fill="{g if built else c["card"]}" stroke="{g}" stroke-width="2"/>')
        o.append(text(MID, y + 4.5, f"{i}", 12, c["card"] if built else g, "700", "middle", MONO))

        top = y - CARD_H / 2
        o.append(f'<rect x="{CARD_X}" y="{top}" width="{CARD_W}" height="{CARD_H}" rx="10" '
                 f'fill="{c["card"]}" stroke="{c["border"]}"/>')
        o.append(f'<rect x="{CARD_X}" y="{top}" width="5" height="{CARD_H}" rx="2.5" fill="{g}"/>')
        o.append(text(CARD_X + 20, y - 4, title, 15, c["text"], "700"))
        o.append(text(CARD_X + 20, y + 15, desc, 12.5, c["muted"]))

        label = KIND_LABEL[kind]
        bw = 84  # fixed widths keep the badges aligned in columns
        bx = CARD_X + CARD_W - 14 - bw
        o.append(f'<rect x="{bx}" y="{y - 11}" width="{bw}" height="22" rx="11" fill="{c[kind + "_bg"]}"/>')
        o.append(text(bx + bw / 2, y + 4, label, 11.5, c[kind + "_fg"], "600", "middle"))

        st = STATUS_LABEL[status]
        sw = 92
        sx = bx - 8 - sw
        o.append(f'<rect x="{sx}" y="{y - 11}" width="{sw}" height="22" rx="11" fill="none" '
                 f'stroke="{c[status]}" stroke-width="1.2"/>')
        o.append(text(sx + sw / 2, y + 4, st, 11.5, c[status], "600", "middle"))

        # highlight when the climber passes
        o.append(f'<rect x="{CARD_X}" y="{top}" width="{CARD_W}" height="{CARD_H}" rx="10" '
                 f'fill="{g}" fill-opacity="0.08" stroke="{g}" stroke-width="2.5" opacity="0">'
                 f'{glow_anim(times[i])}</rect>')

    # climber dot
    motion = (f'<animateMotion dur="{DUR}s" repeatCount="indefinite" path="{path}" calcMode="linear" '
              f'keyPoints="0;0;1;1" keyTimes="0;{t0};{t1};1"/>')
    o.append(f'<g><circle r="15" fill="{c["accent"]}" opacity="0.22"/>'
             f'<circle r="7" fill="{c["accent"]}"/>{motion}</g>')

    # trigger at the bottom
    ty = ybot + 52
    o.append(f'<rect x="{MID - 200}" y="{ty}" width="400" height="34" rx="17" fill="{c["card"]}" '
             f'stroke="{c["border"]}"/>')
    o.append(text(MID, ty + 22, "▲ Trigger:  fixer run  ·  issue label  ·  red CI", 13, c["text"], "600", "middle"))

    # legend
    ly = ty + 68
    o.append(text(40, ly, "Loops back", 13, c["text"], "700"))
    for k, (letter, _, _, _, desc) in enumerate(LOOPS):
        x, yy = 40 + (k % 2) * 440, ly + 26 + (k // 2) * 26
        o.append(f'<circle cx="{x + 10}" cy="{yy - 4}" r="10" fill="{c["bg"]}" stroke="{c["fix"]}" stroke-width="1.5"/>')
        o.append(text(x + 10, yy, letter, 11, c["fix"], "700", "middle"))
        o.append(text(x + 30, yy, desc, 13, c["muted"]))

    gy = ly + 92
    o.append(text(40, gy, "Phases", 13, c["text"], "700"))
    x = 110
    for key, name in GROUPS:
        o.append(f'<rect x="{x}" y="{gy - 11}" width="12" height="12" rx="3" fill="{c[key]}"/>')
        o.append(text(x + 18, gy, name, 13, c["muted"]))
        x += 32 + len(name) * 8
    x += 20
    for kind in ("code", "cheap", "llm"):
        label = KIND_LABEL[kind]
        bw = len(label) * 7.2 + 18
        o.append(f'<rect x="{x}" y="{gy - 15}" width="{bw}" height="20" rx="10" fill="{c[kind + "_bg"]}"/>')
        o.append(text(x + bw / 2, gy, label, 11.5, c[kind + "_fg"], "600", "middle"))
        x += bw + 8

    by = gy + 26
    o.append(f'<rect x="40" y="{by}" width="{W - 80}" height="40" rx="10" fill="{c["card"]}" stroke="{c["border"]}"/>')
    o.append(text(W / 2, by + 25, "Guardrails on every rung:  request & time budgets  ·  stuck detection  ·  "
                  "provider failover  ·  give up with a report", 13, c["muted"], "normal", "middle"))

    o.append("</svg>")
    return "\n".join(o)


def build_roadmap(theme: str) -> str:
    """Simple ladder of the engineering phases, with milestone status per rung."""
    c = THEMES[theme]
    n = len(ROADMAP)
    w, top_y, step = 860, 200, 58
    rl, rr = 110, 170
    mid = (rl + rr) / 2
    cx, cw, ch = 200, 620, 46
    dur = 12
    ys = [top_y + (n - i) * step for i in range(1, n + 1)]  # ys[0] = bottom rung
    ybot, ytop = ys[0], ys[-1]
    h = ybot + 130

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
         f'role="img" aria-label="Code Fixer build roadmap: {n} engineering phases from '
         f'{ROADMAP[0][0]} to {ROADMAP[-1][0]}, with the status of each">']
    o.append(f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="14" fill="{c["bg"]}" stroke="{c["border"]}"/>')
    o.append(text(40, 52, "Code Fixer — build roadmap", 24, c["text"], "700"))
    o.append(text(40, 78, f"{n} engineering phases. Each one is a milestone.", 14, c["muted"]))

    # progress (top right)
    done = sum(r[2] == "done" for r in ROADMAP)
    building = sum(r[2] == "building" for r in ROADMAP)
    px, pw = w - 300, 260
    o.append(text(px + pw, 40, ROADMAP_MILESTONE, 12.5, c["next"], "600", "end"))
    o.append(text(px, 66, f"Done {done} / {n} phases", 13, c["text"], "700"))
    o.append(f'<rect x="{px}" y="76" width="{pw}" height="8" rx="4" fill="{c["code_bg"]}"/>')
    seg = pw / n
    if done:
        o.append(f'<rect x="{px}" y="76" width="{seg * done}" height="8" rx="4" fill="{c["done"]}"/>')
    if building:
        o.append(f'<rect x="{px + seg * done}" y="76" width="{seg * building}" height="8" rx="4" fill="{c["building"]}"/>')

    # goal at the top
    o.append(f'<rect x="{mid - 100}" y="{ytop - 76}" width="200" height="34" rx="17" fill="{c["ship"]}" opacity="0.15"/>')
    o.append(f'<rect x="{mid - 100}" y="{ytop - 76}" width="200" height="34" rx="17" fill="none" '
             f'stroke="{c["ship"]}" stroke-width="1.5"/>')
    o.append(text(mid, ytop - 54, "★ Production-ready agent", 14, c["ship"], "700", "middle"))

    for x in (rl, rr):
        o.append(f'<line x1="{x}" y1="{ytop - 32}" x2="{x}" y2="{ybot + 32}" stroke="{c["rail"]}" '
                 f'stroke-width="6" stroke-linecap="round"/>')

    start, end = 0.04, 0.86
    for i, (title, desc, status) in enumerate(ROADMAP, start=1):
        y = ys[i - 1]
        col = c[status]
        o.append(f'<line x1="{rl}" y1="{y}" x2="{rr}" y2="{y}" stroke="{c["rail"]}" stroke-width="6" stroke-linecap="round"/>')
        o.append(f'<line x1="{rr}" y1="{y}" x2="{cx}" y2="{y}" stroke="{c["rail"]}" stroke-width="1.5"/>')

        if status == "next":  # pulsing ring on the current milestone
            o.append(f'<circle cx="{mid}" cy="{y}" r="15" fill="none" stroke="{col}" stroke-width="2">'
                     f'<animate attributeName="r" values="15;24;15" dur="2s" repeatCount="indefinite"/>'
                     f'<animate attributeName="opacity" values="0.9;0;0.9" dur="2s" repeatCount="indefinite"/></circle>')
        filled = status == "done"
        o.append(f'<circle cx="{mid}" cy="{y}" r="15" fill="{col if filled else c["card"]}" stroke="{col}" stroke-width="2"/>')
        o.append(text(mid, y + 4.5, f"{i:02d}", 11.5, c["card"] if filled else col, "700", "middle", MONO))

        tp = y - ch / 2
        border = col if status in ("next", "building") else c["border"]
        o.append(f'<rect x="{cx}" y="{tp}" width="{cw}" height="{ch}" rx="10" fill="{c["card"]}" stroke="{border}"/>')
        o.append(text(cx + 18, y - 3, title, 15, c["text"], "700"))
        o.append(text(cx + 18, y + 14, desc, 12.5, c["muted"]))

        st = STATUS_LABEL[status]
        sw = 96
        sx = cx + cw - 14 - sw
        o.append(f'<rect x="{sx}" y="{y - 11}" width="{sw}" height="22" rx="11" '
                 f'fill="{col if filled else "none"}" fill-opacity="{0.15 if filled else 1}" '
                 f'stroke="{col}" stroke-width="1.2"/>')
        o.append(text(sx + sw / 2, y + 4, st, 11.5, col, "600", "middle"))

        hit = start + (end - start) * (i - 1) / (n - 1)
        o.append(f'<rect x="{cx}" y="{tp}" width="{cw}" height="{ch}" rx="10" fill="{c["accent"]}" '
                 f'fill-opacity="0.07" stroke="{c["accent"]}" stroke-width="2" opacity="0">'
                 f'{glow_anim([hit], dur)}</rect>')

    # climber
    o.append(f'<g><circle r="14" fill="{c["accent"]}" opacity="0.22"/><circle r="6.5" fill="{c["accent"]}"/>'
             f'<animateMotion dur="{dur}s" repeatCount="indefinite" path="M{mid},{ybot} L{mid},{ytop}" '
             f'calcMode="linear" keyPoints="0;0;1;1" keyTimes="0;{start};{end};1"/></g>')

    # start + legend
    sy = ybot + 48
    o.append(f'<rect x="{mid - 90}" y="{sy}" width="180" height="32" rx="16" fill="{c["card"]}" stroke="{c["done"]}"/>')
    o.append(text(mid, sy + 21, "▲ Start: plan & design ✓", 12.5, c["done"], "600", "middle"))
    lx = mid + 130
    for key in ("done", "building", "next", "planned"):
        o.append(text(lx, sy + 21, STATUS_LABEL[key], 12.5, c[key], "600"))
        lx += 110
    o.append(text(w - 40, h - 22, "Updated after every milestone", 11.5, c["muted"], "normal", "end"))

    o.append("</svg>")
    return "\n".join(o)


def build_layout(theme: str) -> str:
    """Folder map of the monorepo: frontend on top, backend lanes, support folders below."""
    c = THEMES[theme]
    w, h = 960, 720
    pad, chip_w, chip_h, gap = 59, 132, 54, 10

    def chip(x, y, name, desc, color):
        return (f'<rect x="{x}" y="{y}" width="{chip_w}" height="{chip_h}" rx="9" fill="{c["card"]}" '
                f'stroke="{c["border"]}"/>'
                f'<rect x="{x}" y="{y + 10}" width="3.5" height="{chip_h - 20}" rx="1.75" fill="{color}"/>'
                + text(x + 13, y + 23, name, 13, c["text"], "700", family=MONO)
                + text(x + 13, y + 41, desc, 11.5, c["muted"]))

    def box(x, y, bw, bh, title, sub, color):
        return (f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="12" fill="{color}" fill-opacity="0.05" '
                f'stroke="{color}" stroke-opacity="0.6" stroke-width="1.5"/>'
                + text(x + 18, y + 27, title, 15, color, "700", family=MONO)
                + text(x + 18 + len(title) * 9.4 + 10, y + 27, sub, 12.5, c["muted"]))

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
         f'role="img" aria-label="Code Fixer project layout: Next.js frontend talking to a Python backend '
         f'over REST and live events, with backend modules grouped into lanes">']
    o.append(f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="14" fill="{c["bg"]}" stroke="{c["border"]}"/>')
    o.append(text(40, 52, "Code Fixer — project layout", 24, c["text"], "700"))
    o.append(text(40, 78, "A monorepo: a Next.js dashboard on top of a Python agent backend.", 14, c["muted"]))

    # frontend
    fy = 104
    o.append(box(40, fy, w - 80, 112, "frontend/src/", "Next.js · Tailwind · shadcn/ui", c["prepare"]))
    for k, (name, desc) in enumerate(LAYOUT_FRONTEND):
        o.append(chip(pad + k * (chip_w + gap), fy + 44, name, desc, c["prepare"]))

    # connection: REST down, SSE up (flowing dashes)
    ay1, ay2 = fy + 112, fy + 112 + 58
    for x, y1, y2, label in ((w / 2 - 70, ay1 + 4, ay2 - 4, "REST /api"), (w / 2 + 70, ay2 - 4, ay1 + 4, "live events (SSE)")):
        o.append(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{c["accent"]}" stroke-width="2" '
                 f'stroke-dasharray="5 4" marker-end="url(#lay-arrow)">'
                 f'<animate attributeName="stroke-dashoffset" from="18" to="0" dur="1s" repeatCount="indefinite"/></line>')
        o.append(text(x + (-12 if x < w / 2 else 12), (ay1 + ay2) / 2 + 4, label, 12, c["accent"], "600",
                      "end" if x < w / 2 else "start"))
    o.insert(1, f'<defs><marker id="lay-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" '
                f'markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{c["accent"]}"/></marker></defs>')

    # backend lanes
    by = ay2
    rows = max(len(m) for _, _, m in LAYOUT_BACKEND)
    bh = 44 + 26 + rows * (chip_h + gap) + 6
    o.append(box(40, by, w - 80, bh, "backend/fixer/", "Python · FastAPI · Docker", c["understand"]))
    for k, (lane, key, mods) in enumerate(LAYOUT_BACKEND):
        x = pad + k * (chip_w + gap)
        o.append(text(x + 2, by + 58, lane.upper(), 11, c[key], "700", extra='letter-spacing="0.6"'))
        for r, (name, desc) in enumerate(mods):
            o.append(chip(x, by + 70 + r * (chip_h + gap), name, desc, c[key]))

    # support folders
    sy = by + bh + 24
    sw = (w - 80 - 2 * 16) / 3
    for k, (name, desc) in enumerate(LAYOUT_OTHER):
        x = 40 + k * (sw + 16)
        o.append(f'<rect x="{x}" y="{sy}" width="{sw}" height="58" rx="10" fill="{c["card"]}" stroke="{c["border"]}"/>')
        o.append(text(x + 18, sy + 25, name, 13.5, c["text"], "700", family=MONO))
        o.append(text(x + 18, sy + 44, desc, 12, c["muted"]))

    o.append("</svg>")
    out = "\n".join(o)
    total_h = sy + 58 + 28
    return out.replace(f'height="{h}" viewBox="0 0 {w} {h}"', f'height="{total_h}" viewBox="0 0 {w} {total_h}"', 1) \
              .replace(f'width="{w - 2}" height="{h - 2}"', f'width="{w - 2}" height="{total_h - 2}"', 1)


if __name__ == "__main__":
    for name in THEMES:
        for stem, fn in (("build-roadmap", build_roadmap), ("harness-ladder", build),
                         ("project-layout", build_layout)):
            out = OUT / f"{stem}-{name}.svg"
            out.write_text(fn(name), encoding="utf-8")
            print("wrote", out)
