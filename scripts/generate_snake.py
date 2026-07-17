#!/usr/bin/env python3
"""
Generate a premium animated snake SVG from a GitHub user's LIVE contribution
calendar.

Approach
--------
Instead of a live snake AI (which traps or livelocks), we build the snake's
route as a SIMPLE PATH -- one that never reuses a cell. The route greedily hops
to the nearest not-yet-eaten contribution, and each connector between
contributions is routed only through not-yet-visited cells, which keeps the
entire route self-intersection-free by construction.

Consequences, all guaranteed rather than hoped for:
  * a trailing body of ANY length is L consecutive DISTINCT cells -> it can
    never overlap itself,
  * consecutive route cells are always adjacent -> motion is a smooth glide,
  * the route targets lit tiles and only crosses empties as short connectors,
  * the snake grows one segment per contribution eaten.

Body: tapered gold->deep-gold ribbon with a soft-glowing head.

Data: GitHub GraphQL API. Auth: GH_TOKEN / GITHUB_TOKEN (Actions token reads a
public calendar; if empty, use a classic PAT with `read:user`).
Output: SVG to argv[1] (default: dist/contribution-matrix.svg).
"""

import json
import os
import sys
import urllib.request
from collections import deque

# ---- Palette ----------------------------------------------------------------
DOTS = ["#1f1c12", "#5c4a12", "#8a6b1a", "#d8a93c", "#F5D061"]
HEAD_COLOR = "#FFE9A8"
BODY_COLOR = "#F5D061"
TAIL_COLOR = "#7d6017"
EMPTY = DOTS[0]

# ---- Geometry ---------------------------------------------------------------
CELL, GAP, MARGIN = 11, 3, 16
PITCH = CELL + GAP

# ---- Route mode -------------------------------------------------------------
#   "sweep" : weaves the whole board, eats EVERY contribution, never overlaps,
#             smooth. Crosses empty tiles between contributions (unavoidable if
#             you want to eat them all without ever crossing yourself).
#   "hunt"  : skips empties and heads only for contributions, never overlaps,
#             but LEAVES some contributions uneaten (whatever its trail walls
#             off). Looks like a hunter; the board won't fully clear.
PATH_MODE = "sweep"

# ---- Snake / animation ------------------------------------------------------
BASE_LEN = 4
MAX_LEN = 14
FEAST_STEP = 0.090    # seconds per move INTO a lit tile (deliberate)
SKIM_STEP = 0.030     # seconds per move across an empty tile (quick skim)
END_HOLD = 1.6        # pause on the cleared board before the loop

LEVEL_MAP = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
             "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

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


# ---- Data -------------------------------------------------------------------
def fetch_calendar(login, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": GRAPHQL, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "premium-snake-generator"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL error: {payload['errors']}")
    weeks_raw = (payload["data"]["user"]["contributionsCollection"]
                 ["contributionCalendar"]["weeks"])
    return [[{"weekday": d["weekday"], "level": LEVEL_MAP.get(d["contributionLevel"], 0)}
             for d in w["contributionDays"]] for w in weeks_raw]


def build_grid(weeks):
    grid = {}
    for w, days in enumerate(weeks):
        for d in days:
            grid[(w, d["weekday"])] = d["level"]
    return grid, len(weeks)


# ---- Grid helpers -----------------------------------------------------------
def neighbors(cell, cells):
    w, d = cell
    for dw, dd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        n = (w + dw, d + dd)
        if n in cells:
            yield n


def bfs_unvisited(current, targets, visited, cells):
    """Shortest walk from current to the nearest cell in `targets`, travelling
    only through cells NOT already visited. Returns [current,...,target] or None."""
    prev = {current: None}
    q = deque([current])
    while q:
        c = q.popleft()
        if c in targets and c != current:
            path, x = [], c
            while x is not None:
                path.append(x)
                x = prev[x]
            return path[::-1]
        for n in neighbors(c, cells):
            if n not in prev and n not in visited:
                prev[n] = c
                q.append(n)
    return None


def serpentine(grid, num_weeks):
    path = []
    for w in range(num_weeks):
        for d in (range(7) if w % 2 == 0 else range(6, -1, -1)):
            if (w, d) in grid:
                path.append((w, d))
    return path


def build_path(grid, num_weeks):
    """A self-avoiding route that hops between contributions. Because connectors
    only cross unvisited cells and every stepped cell is marked visited, the
    whole route is a simple (non-repeating) path."""
    cells = set(grid)
    foods = {c for c, v in grid.items() if v > 0}
    if not foods:
        return serpentine(grid, num_weeks)

    start = min(foods, key=lambda c: (c[0], c[1]))
    path = [start]
    visited = {start}
    remaining = set(foods)
    remaining.discard(start)
    current = start

    while remaining:
        seg = bfs_unvisited(current, remaining, visited, cells)
        if seg is None:                     # rest is walled off by our own trail
            break
        for c in seg[1:]:
            path.append(c)
            visited.add(c)
            remaining.discard(c)            # foods crossed en route are eaten too
        current = seg[-1]
    return path


# ---- Rendering --------------------------------------------------------------
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
    t = i / max(MAX_LEN - 1, 1)
    if i == 0:
        return CELL + 3, HEAD_COLOR, 1.0, (CELL + 3) / 2
    size = round(CELL + 1 - 4 * t, 2)
    return size, lerp_hex(BODY_COLOR, TAIL_COLOR, t), round(1.0 - 0.45 * t, 3), \
        round(min(size / 2, 4.5), 2)


def build_route(grid, num_weeks):
    if PATH_MODE == "hunt":
        return build_path(grid, num_weeks)
    return serpentine(grid, num_weeks)      # "sweep" (default): full coverage


def generate_svg(grid, num_weeks):
    path = build_route(grid, num_weeks)
    steps = len(path)
    positions = [cell_xy(w, d) for (w, d) in path]

    # variable pacing: dart across empty tiles, slow down to feast on lit ones.
    # times[s] is the clock time when the head arrives at path[s].
    times = [0.0]
    for s in range(1, steps):
        times.append(times[-1] + (FEAST_STEP if grid[path[s]] > 0 else SKIM_STEP))

    eaten, lengths, first_lit_step = set(), [], {}
    for s, c in enumerate(path):
        if grid[c] > 0 and c not in eaten:
            eaten.add(c)
            first_lit_step[c] = s
        lengths.append(min(MAX_LEN, BASE_LEN + len(eaten)))

    move_end = times[-1]
    total = move_end + END_HOLD
    svg_w = MARGIN * 2 + num_weeks * PITCH - GAP
    svg_h = MARGIN * 2 + 7 * PITCH - GAP

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w}" height="{svg_h}" '
           f'viewBox="0 0 {svg_w} {svg_h}" fill="none">']
    out.append('<defs><filter id="glow" x="-70%" y="-70%" width="240%" height="240%">'
               '<feGaussianBlur stdDeviation="2.6" result="b"/>'
               '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
               '</filter></defs>')

    style = ['<style>',
             f'.cell{{width:{CELL}px;height:{CELL}px;rx:2.5px;}}',
             '.food{transform-box:fill-box;transform-origin:center;}']
    style.append('@keyframes seam{0%{opacity:0}1.5%{opacity:1}'
                 f'{pct(move_end, total)}%{{opacity:1}}100%{{opacity:0}}}}')
    body = []

    # base grid
    body.append('<g>')
    for (w, d) in grid:
        x, y = cell_xy(w, d)
        body.append(f'<rect class="cell" x="{x}" y="{y}" fill="{EMPTY}"/>')
    body.append('</g>')

    # contributions that pop + dissolve as the head eats them
    body.append('<g>')
    for (w, d), lvl in grid.items():
        if lvl <= 0 or (w, d) not in first_lit_step:
            continue
        x, y = cell_xy(w, d)
        eat = times[first_lit_step[(w, d)]]
        a = pct(max(eat - 0.03, 0), total)
        mid = pct(eat + FEAST_STEP * 0.35, total)
        b = pct(eat + FEAST_STEP * 1.1, total)
        name = f"eat_{w}_{d}"
        style.append(f'@keyframes {name}{{0%,{a}%{{opacity:1;transform:scale(1)}}'
                     f'{mid}%{{opacity:1;transform:scale(1.35)}}'
                     f'{b}%,100%{{opacity:0;transform:scale(0.2)}}}}')
        body.append(f'<rect class="cell food" x="{x}" y="{y}" fill="{DOTS[lvl]}" '
                    f'style="animation:{name} {total:.2f}s linear infinite"/>')
    body.append('</g>')

    # the snake
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

        css = []
        if appear > 0:
            css.append(f'0%{{transform:{tf(appear)};opacity:0}}')
            jb = max(pct(times[appear], total) - 0.01, 0.01)
            css.append(f'{jb}%{{transform:{tf(appear)};opacity:0}}')
        for s in range(appear, steps):
            css.append(f'{pct(times[s], total)}%{{transform:{tf(s)};opacity:{opacity}}}')
        css.append(f'100%{{transform:{tf(steps-1)};opacity:{opacity}}}')

        style.append(f'@keyframes seg_{i}{{{"".join(css)}}}')
        filt = ' filter="url(#glow)"' if i == 0 else ''
        body.append(f'<rect width="{size}" height="{size}" rx="{rx}" fill="{color}"{filt} '
                    f'opacity="0" style="animation:seg_{i} {total:.2f}s linear infinite"/>')
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
