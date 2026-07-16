#!/usr/bin/env python3
"""
Generate an animated "growing snake" SVG from a GitHub user's LIVE contribution
calendar. The snake hunts the lit contribution cells (not every square), eating
them in an efficient nearest-first order and gaining one body segment per bite.
Matches the VenomX gold/obsidian palette.

Data source: GitHub GraphQL API (contributionsCollection.contributionCalendar).
Auth: reads a token from GH_TOKEN (or GITHUB_TOKEN). The default Actions
GITHUB_TOKEN works for reading a public contribution calendar. If your calendar
comes back empty, supply a classic PAT with `read:user` scope instead.

Output: writes the SVG to the path given as argv[1] (default: dist/contribution-matrix.svg).
"""

import json
import os
import sys
import urllib.request
from collections import deque

# ----------------------------------------------------------------------------
# Palette (matches the README: gold #F5D061 / obsidian #0A0A0A / steel #A6B4C8)
# ----------------------------------------------------------------------------
DOTS = ["#2a2412", "#5c4a12", "#8a6b1a", "#d8a93c", "#F5D061"]
SNAKE_BODY = "#FFF6D8"   # cream trail
SNAKE_HEAD = "#F5D061"   # gold head
EMPTY = DOTS[0]

# ----------------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------------
CELL = 11
GAP = 3
PITCH = CELL + GAP
MARGIN = 14

# ----------------------------------------------------------------------------
# Animation
# ----------------------------------------------------------------------------
BASE_LEN = 4          # snake length before it has eaten anything
MAX_LEN = 18          # cap so it stays a snake, not a boa that swallows the board
TARGET_MOVE = 13.0    # seconds the full traversal should take (drives speed)
MIN_STEP = 0.030      # fastest a cell crossing may be (keeps dense boards visible)
MAX_STEP = 0.085      # slowest a cell crossing may be (keeps sparse boards snappy)
END_HOLD = 1.8        # seconds to hold the finished frame before the loop restarts

LEVEL_MAP = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

GRAPHQL = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            weekday
            contributionCount
            contributionLevel
          }
        }
      }
    }
  }
}
"""


def fetch_calendar(login, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": GRAPHQL, "variables": {"login": login}}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "growing-snake-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)

    if payload.get("errors"):
        raise RuntimeError(f"GraphQL error: {payload['errors']}")

    weeks_raw = (
        payload["data"]["user"]["contributionsCollection"]
        ["contributionCalendar"]["weeks"]
    )
    weeks = []
    for w in weeks_raw:
        days = [
            {"weekday": d["weekday"], "level": LEVEL_MAP.get(d["contributionLevel"], 0)}
            for d in w["contributionDays"]
        ]
        weeks.append(days)
    return weeks


def build_grid(weeks):
    grid = {}
    for w, days in enumerate(weeks):
        for d in days:
            grid[(w, d["weekday"])] = d["level"]
    return grid, len(weeks)


# ----------------------------------------------------------------------------
# Pathfinding: hunt the lit cells instead of sweeping the whole board
# ----------------------------------------------------------------------------
def _neighbors(cell, cells):
    w, d = cell
    for dw, dd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = (w + dw, d + dd)
        if n in cells:
            yield n


def _bfs(start, goal, cells):
    """Shortest grid walk start -> goal over existing cells (4-neighbourhood)."""
    if start == goal:
        return [start]
    prev = {start: None}
    q = deque([start])
    while q:
        c = q.popleft()
        if c == goal:
            break
        for n in _neighbors(c, cells):
            if n not in prev:
                prev[n] = c
                q.append(n)
    if goal not in prev:
        return None
    out, c = [], goal
    while c is not None:
        out.append(c)
        c = prev[c]
    out.reverse()
    return out


def _serpentine(grid, num_weeks):
    path = []
    for w in range(num_weeks):
        rows = range(7) if w % 2 == 0 else range(6, -1, -1)
        for d in rows:
            if (w, d) in grid:
                path.append((w, d))
    return path


def target_path(grid, num_weeks):
    """Nearest-first tour over the lit cells, stitched together with the
    shortest grid walk between each pair. The head only detours through empty
    cells when it has to in order to reach the next contribution."""
    cells = set(grid.keys())
    lit = [c for c, v in grid.items() if v > 0]
    if not lit:
        return _serpentine(grid, num_weeks)

    remaining = set(lit)
    current = min(lit, key=lambda c: (c[0], c[1]))  # top-left-most lit cell
    remaining.discard(current)
    full = [current]

    while remaining:
        nxt = min(remaining, key=lambda c: abs(c[0] - current[0]) + abs(c[1] - current[1]))
        remaining.discard(nxt)
        seg = _bfs(current, nxt, cells)
        if seg is None:            # disconnected (shouldn't happen); jump directly
            seg = [current, nxt]
        full.extend(seg[1:])       # skip the shared cell
        current = nxt

    return full


def cell_xy(w, d):
    return MARGIN + w * PITCH, MARGIN + d * PITCH


def pct(t, total):
    return round(t / total * 100, 4)


def generate_svg(grid, num_weeks):
    path = target_path(grid, num_weeks)
    steps = len(path)
    positions = [cell_xy(w, d) for (w, d) in path]

    # adaptive per-cell speed so the whole run lands near TARGET_MOVE seconds
    step_dur = min(MAX_STEP, max(MIN_STEP, TARGET_MOVE / max(steps, 1)))

    # growth + when each lit cell is first eaten (first time the head lands on it)
    eaten = set()
    lengths = []
    first_lit_step = {}
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
    style = ['<style>']
    style.append(
        f'.cell{{width:{CELL}px;height:{CELL}px;rx:2.5px;}}'
        f'.snake{{width:{CELL}px;height:{CELL}px;rx:3px;}}'
        f'.head{{rx:{CELL/2}px;}}'
    )
    body = []

    # static empty layer (eaten cells fade back to this)
    body.append('<g>')
    for (w, d) in grid:
        x, y = cell_xy(w, d)
        body.append(f'<rect class="cell" x="{x}" y="{y}" fill="{EMPTY}"/>')
    body.append('</g>')

    # lit cells that get eaten, fading out as the head reaches them
    body.append('<g>')
    for (w, d), lvl in grid.items():
        if lvl <= 0 or (w, d) not in first_lit_step:
            continue
        x, y = cell_xy(w, d)
        eat = pct(first_lit_step[(w, d)] * step_dur, total)
        name = f"eat_{w}_{d}"
        style.append(
            f'@keyframes {name}{{0%,{max(eat-0.01,0)}%{{opacity:1}}'
            f'{eat}%,100%{{opacity:0}}}}'
        )
        body.append(
            f'<rect class="cell" x="{x}" y="{y}" fill="{DOTS[lvl]}" opacity="1" '
            f'style="animation:{name} {total:.2f}s linear infinite"/>'
        )
    body.append('</g>')

    # the growing snake, head first
    body.append('<g>')
    for i in range(MAX_LEN):
        appear = i
        while appear < steps and lengths[appear] <= i:
            appear += 1
        if appear >= steps:
            continue

        frames = []
        if appear > 0:
            px0, py0 = positions[0]
            frames.append(f'0%{{transform:translate({px0}px,{py0}px);opacity:0}}')
            just_before = max(pct(appear * step_dur, total) - 0.01, 0.01)
            frames.append(f'{just_before}%{{opacity:0}}')

        for s in range(appear, steps):
            px, py = positions[s - i]
            frames.append(f'{pct(s*step_dur, total)}%{{transform:translate({px}px,{py}px);opacity:1}}')

        pxl, pyl = positions[(steps - 1) - i]
        frames.append(f'100%{{transform:translate({pxl}px,{pyl}px);opacity:1}}')

        name = f"seg_{i}"
        style.append(f'@keyframes {name}{{{"".join(frames)}}}')
        cls = "snake head" if i == 0 else "snake"
        fill = SNAKE_HEAD if i == 0 else SNAKE_BODY
        body.append(
            f'<rect class="{cls}" fill="{fill}" opacity="0" '
            f'style="animation:{name} {total:.2f}s linear infinite"/>'
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
    lit = sum(1 for v in grid.values() if v > 0)
    print(f"Wrote {out_path}: {num_weeks} weeks, {len(grid)} cells, {lit} lit.")


if __name__ == "__main__":
    main()
