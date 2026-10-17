"""Generate the animated harness-ladder diagrams used in README.md.

Run:  python3 docs/assets/build_ladder.py
Writes harness-ladder-light.svg and harness-ladder-dark.svg next to this file.
Edit PHASES / LOOPS below to change the diagram.

Progress tracking: when a milestone is reached, update MILESTONE and the
status of each phase ("planned" | "building" | "done"), then re-run this script.
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent

# Current milestone shown in the header (see Plan.md §12).
MILESTONE = "Milestone 0 · Planning"

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
STATUS_LABEL = {"planned": "○ planned", "building": "◐ building", "done": "✓ done"}

THEMES = {
    "light": {
        "bg": "#f6f8fa", "border": "#d0d7de", "card": "#ffffff", "text": "#1f2328",
        "muted": "#59636e", "rail": "#8c959f", "accent": "#bf3989",
        "prepare": "#0969da", "understand": "#8250df", "fix": "#bc4c00", "ship": "#1a7f37",
        "code_bg": "#eaeef2", "code_fg": "#59636e", "cheap_bg": "#ddf4ff", "cheap_fg": "#0969da",
        "llm_bg": "#fbefff", "llm_fg": "#8250df",
        "planned": "#8c959f", "building": "#9a6700", "done": "#1a7f37",
    },
    "dark": {
        "bg": "#161b22", "border": "#30363d", "card": "#0d1117", "text": "#e6edf3",
        "muted": "#9198a1", "rail": "#6e7681", "accent": "#db61a2",
        "prepare": "#4493f8", "understand": "#ab7df8", "fix": "#f0883e", "ship": "#3fb950",
        "code_bg": "#21262d", "code_fg": "#9198a1", "cheap_bg": "#0c2d6b", "cheap_fg": "#79c0ff",
        "llm_bg": "#271052", "llm_fg": "#d2a8ff",
        "planned": "#6e7681", "building": "#d29922", "done": "#3fb950",
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


def glow_anim(hit_times) -> str:
    pts = [(0.0, 0.0)]
    for n, t in enumerate(sorted(hit_times)):
        pts += [(t - 0.012, 0.0 if n == 0 else 0.3), (t, 1.0), (t + 0.05, 0.3)]
    pts += [(0.97, 0.3), (1.0, 0.0)]
    kt = ";".join(f"{t:.4f}" for t, _ in pts)
    vals = ";".join(f"{v}" for _, v in pts)
    return (f'<animate attributeName="opacity" dur="{DUR}s" repeatCount="indefinite" '
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


if __name__ == "__main__":
    for name in THEMES:
        out = OUT / f"harness-ladder-{name}.svg"
        out.write_text(build(name), encoding="utf-8")
        print("wrote", out)
