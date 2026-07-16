#!/usr/bin/env python3
"""
Generate a premium animated "growing snake" SVG from a GitHub user's LIVE
contribution calendar.

Design notes
------------
The snake travels a SELF-AVOIDING route (a boustrophedon Hamiltonian path over
the calendar). Because no cell is ever revisited, the body can never overlap
itself and the motion stays a smooth continuous glide with clean turns. It grows
one segment every time it eats a lit contribution cell; eaten cells dissolve back
into the grid. The body is a tapered gold->cream ribbon with a soft-glowing head.

Data source: GitHub GraphQL API (contributionsCollection.contributionCalendar).
Auth: reads a token from GH_TOKEN (or GITHUB_TOKEN). The default Actions
GITHUB_TOKEN works for a public contribution calendar; if yours comes back empty,
use a classic PAT with `read:user` scope.

Output: SVG written to argv[1] (default: dist/contribution-matrix.svg).
"""

import json
import os
import sys
import urllib.request

# ----------------------------------------------------------------------------
# Palette (README: gold #F5D061 / obsidian #0A0A0A / steel #A6B4C8)
# ----------------------------------------------------------------------------
DOTS = ["#1f1c12", "#5c4a12", "#8a6b1a", "#d8a93c", "#F5D061"]
HEAD_COLOR = "#FFE9A8"   # bright warm gold
BODY_COLOR = "#F5D061"   # gold
TAIL_COLOR = "#8a6b1a"   # deep gold, ribbon fades toward this at the tail
EMPTY = DOTS[0]

# ----------------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------------
CELL = 11
GAP = 3
PITCH = CELL + GAP
MARGIN = 16

# ----------------------------------------------------------------------------
# Animation
# ----------------------------------------------------------------------------
BASE_LEN = 5          # length before eating anything
MAX_LEN = 16          # cap so it reads as a snake, not a python
TARGET_MOVE = 14.0    # seconds for the whole run (drives per-cell speed)
MIN_STEP = 0.032      # fastest cell crossing
MAX_STEP = 0.070      # slowest cell crossing
END_HOLD = 1.4        # pause on the finished board before the crossfade/loop

LEVEL_MAP = {
    "NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4,
}

GRAPHQL = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { weekday contributionCount contributionLevel } }
      }
    }
  }
}
"""


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def fetch_calendar(login, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": GRAPHQL, "variables": {"login": login}}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "premium-snake-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL error: {payload['errors']}")
    weeks_raw = (payload["data"]["user"]["contributionsCollection"]
                 ["contributionCalendar"]["weeks"])
    return [
        [{"weekday": d["weekday"], "level": LEVEL_MAP.get(d["contributionLevel"], 0)}
         for d in w["contributionDays"]]
        for w in weeks_raw
    ]


def build_grid(weeks):
    grid = {}
    for w, days in enumerate(weeks):
        for d in days:
            grid[(w, d["weekday"])] = d["level"]
    return grid, len(weeks)


# ----------------------------------------------------------------------------
# Self-avoiding route: down col 0, up col 1, down col 2, ... Every cell is
# visited exactly once and consecutive cells are neighbours, so the snake body
# is always a clean non-overlapping chain.
# ----------------------------------------------------------------------------
def route(grid, num_weeks):
    path = []
    for w in range(num_weeks):
        rows = range(7) if w % 2 == 0 else range(6, -1, -1)
        for d in rows:
            if (w, d) in grid:
                path.append((w, d))
    return path


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def cell_xy(w, d):
    return MARGIN + w * PITCH, MARGIN + d * PITCH


def pct(t, total):
    return round(t / total * 100, 4)


def lerp_hex(a, b, t):
    a, b = a.lstrip("#"), b.lstrip("#")
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(round(ca[k] + (cb[k] - ca[k]) * t) for k in range(3))


def seg_look(i):
    """Per-segment size / colour / opacity, tapering from head to tail."""
    t = i / max(MAX_LEN - 1, 1)
    if i == 0:
        return CELL + 3, HEAD_COLOR, 1.0, (CELL + 3) / 2      # round glowing head
    size = round(CELL + 1 - 4 * t, 2)                          # 12 -> ~8
    color = lerp_hex(BODY_COLOR, TAIL_COLOR, t)
    opacity = round(1.0 - 0.45 * t, 3)                         # 1.0 -> ~0.55
    rx = round(min(size / 2, 4.5), 2)
    return size, color, opacity, rx


# ----------------------------------------------------------------------------
# SVG
# ----------------------------------------------------------------------------
def generate_svg(grid, num_weeks):
    path = route(grid, num_weeks)
    steps = len(path)
    positions = [cell_xy(w, d) for (w, d) in path]
    step_dur = min(MAX_STEP, max(MIN_STEP, TARGET_MOVE / max(steps, 1)))

    eaten, lengths, first_lit_step = set(), [], {}
    for s, c in enumerate(path):
        if grid[c] > 0 and c not in eaten:
            eaten.add(c)
            first_lit_step[c] = s
        lengths.append(min(MAX_LEN, BASE_LEN + len(eaten)))

    move_end = (steps - 1) * step_dur
    total = move_end + END_HOLD

    svg_w = MARGIN * 2 + num_weeks * PITCH - GAP
    svg_h = MARGIN * 2 + 7 * PITCH - GAP

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}" fill="none">'
    ]

    # defs: soft glow for the head, gradient sheen for the board is skipped for size
    out.append(
        '<defs>'
        '<filter id="glow" x="-60%" y="-60%" width="220%" height="220%">'
        '<feGaussianBlur stdDeviation="2.4" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
        '</filter>'
        '</defs>'
    )

    style = ['<style>', f'.cell{{width:{CELL}px;height:{CELL}px;rx:2.5px;}}']

    # crossfade at the loop seam so the reset isn't a hard jump
    style.append(
        '@keyframes seam{0%{opacity:0}2.5%{opacity:1}'
        f'{pct(move_end, total)}%{{opacity:1}}100%{{opacity:0}}}}'
    )

    body = []

    # --- static empty layer -------------------------------------------------
    body.append('<g>')
    for (w, d) in grid:
        x, y = cell_xy(w, d)
        body.append(f'<rect class="cell" x="{x}" y="{y}" fill="{EMPTY}"/>')
    body.append('</g>')

    # --- lit cells that dissolve as they are eaten --------------------------
    body.append('<g>')
    for (w, d), lvl in grid.items():
        if lvl <= 0 or (w, d) not in first_lit_step:
            continue
        x, y = cell_xy(w, d)
        eat = first_lit_step[(w, d)] * step_dur
        a = pct(max(eat - 0.02, 0), total)
        b = pct(eat + step_dur * 0.9, total)      # gentle dissolve, not a snap
        name = f"eat_{w}_{d}"
        style.append(f'@keyframes {name}{{0%,{a}%{{opacity:1}}{b}%,100%{{opacity:0}}}}')
        body.append(
            f'<rect class="cell" x="{x}" y="{y}" fill="{DOTS[lvl]}" '
            f'style="animation:{name} {total:.2f}s linear infinite"/>'
        )
    body.append('</g>')

    # --- the snake (crossfaded group) ---------------------------------------
    body.append(f'<g style="animation:seam {total:.2f}s linear infinite">')
    for i in range(MAX_LEN):
        appear = i
        while appear < steps and lengths[appear] <= i:
            appear += 1
        if appear >= steps:
            continue

        size, color, opacity, rx = seg_look(i)
        inset = (CELL - size) / 2

        def tf(step):
            px, py = positions[step - i]
            return f'translate({round(px + inset, 2)}px,{round(py + inset, 2)}px)'

        frames = []
        if appear > 0:
            frames.append(f'0%{{transform:{tf(0)};opacity:0}}')
            jb = max(pct(appear * step_dur, total) - 0.01, 0.01)
            frames.append(f'{jb}%{{opacity:0}}')
        for s in range(appear, steps):
            frames.append(f'{pct(s*step_dur, total)}%{{transform:{tf(s)};opacity:{opacity}}}')
        frames.append(f'100%{{transform:{tf(steps-1)};opacity:{opacity}}}')

        name = f"seg_{i}"
        style.append(f'@keyframes {name}{{{"".join(frames)}}}')
        filt = ' filter="url(#glow)"' if i == 0 else ''
        body.append(
            f'<rect width="{size}" height="{size}" rx="{rx}" fill="{color}"{filt} '
            f'opacity="0" style="animation:{name} {total:.2f}s linear infinite"/>'
        )
    body.append('</g>')

    style.append('</style>')
    out.extend(style)
    out.extend(body)
    out.append('</svg>')
    return "\n".join(out)


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "dist/contribution-matrix.svg"
    login = os.environ.get("GH_USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not login:
        sys.exit("Set GH_USERNAME (or run inside Actions where GITHUB_REPOSITORY_OWNER is set).")
    if not token:
        sys.exit("Set GH_TOKEN / GITHUB_TOKEN.")

    weeks = fetch_calendar(login, token)
    grid, num_weeks = build_grid(weeks)
    if not grid:
        sys.exit("Contribution calendar came back empty — try a PAT with read:user scope.")

    svg = generate_svg(grid, num_weeks)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(svg)
    print(f"Wrote {out_path}: {num_weeks} weeks, {len(grid)} cells, "
          f"{sum(1 for v in grid.values() if v > 0)} lit.")


if __name__ == "__main__":
    main()
