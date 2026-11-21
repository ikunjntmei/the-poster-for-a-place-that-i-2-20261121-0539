#!/usr/bin/env python3
"""VELMARA -- a travel poster for a place that does not exist.

A pure-standard-library program (Python 3.13) that paints a 1024x1024
travel poster for Velmara, a harbour town on a crescent bay where twice
a day the tide climbs the sky, and writes it to /output/entry.png.

Velmara's promise: an evening in a town where the sea goes up instead
of out. Its landmark is the Tide Stair, a white stone stairway strung
with warm lanterns, climbing from the harbour steps to a small
lighthouse on the cliff top, beside a slow waterfall of golden light
that rises from the harbour and dissolves into the clouds.

Everything is drawn in code: gradients, glows, silhouettes, the stair,
the lighthouse, the boats and birds, and the letters of VELMARA from
bitmap letterforms defined below. The PNG is encoded by hand (raw RGB
scanlines, zlib, PNG chunks). No files are read, no network, no clock:
the output is byte-identical on every run.
"""

import math
import os
import random
import struct
import zlib

W = 1024
H = 1024
OUT_PATH = "/output/entry.png"
SEED = 20261121
HORIZON = 600

# --- palette: deep teal, amber gold, cream, one soft coral accent -------
TEAL_DEEP = (12, 52, 66)
TEAL_MID = (26, 92, 100)
AMBER_HORIZON = (233, 170, 95)
SUN_CORE = (249, 206, 98)
SUN_GLOW = (242, 169, 59)
SEA_TOP = (15, 74, 86)
SEA_DEEP = (7, 42, 51)
CREAM = (247, 232, 200)
CLIFF = (243, 230, 196)
CLIFF_SHADOW = (206, 184, 146)
HEADLAND = (10, 40, 48)
DARK = (14, 40, 48)
LANTERN = (255, 196, 107)
CORAL = (224, 120, 86)
MIST = (238, 222, 190)
STONE = (235, 222, 190)

# --- framebuffer ---------------------------------------------------------
buf = bytearray(W * H * 3)


def _off(x, y):
    return (y * W + x) * 3


def put(x, y, color):
    """Set one pixel, silently ignoring out-of-bounds coordinates."""
    if 0 <= x < W and 0 <= y < H:
        o = _off(x, y)
        buf[o], buf[o + 1], buf[o + 2] = color


def blend(x, y, color, alpha):
    """Blend one pixel toward color; alpha 0..255."""
    if 0 <= x < W and 0 <= y < H and alpha > 0:
        o = _off(x, y)
        inv = 255 - alpha
        buf[o] = (color[0] * alpha + buf[o] * inv) // 255
        buf[o + 1] = (color[1] * alpha + buf[o + 1] * inv) // 255
        buf[o + 2] = (color[2] * alpha + buf[o + 2] * inv) // 255


def fill_run(y, x0, x1, color):
    """Fill a horizontal run of one row with a solid color (fast)."""
    if y < 0 or y >= H:
        return
    x0 = max(0, x0)
    x1 = min(W - 1, x1)
    if x1 < x0:
        return
    o = _off(x0, y)
    n = x1 - x0 + 1
    buf[o:o + n * 3] = bytes(color) * n


def blend_run(y, x0, x1, color, alpha):
    """Blend a horizontal run of one row toward a color."""
    if alpha <= 0 or y < 0 or y >= H:
        return
    x0 = max(0, x0)
    x1 = min(W - 1, x1)
    if x1 < x0:
        return
    inv = 255 - alpha
    r, g, b = color
    for x in range(x0, x1 + 1):
        o = _off(x, y)
        buf[o] = (r * alpha + buf[o] * inv) // 255
        buf[o + 1] = (g * alpha + buf[o + 1] * inv) // 255
        buf[o + 2] = (b * alpha + buf[o + 2] * inv) // 255


def fill_rect(x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(H, y1 + 1)):
        fill_run(y, x0, x1, color)


def blend_rect(x0, y0, x1, y1, color, alpha):
    for y in range(max(0, y0), min(H, y1 + 1)):
        blend_run(y, x0, x1, color, alpha)


def lerp_color(c0, c1, t):
    return (round(c0[0] + (c1[0] - c0[0]) * t),
            round(c0[1] + (c1[1] - c0[1]) * t),
            round(c0[2] + (c1[2] - c0[2]) * t))


def vgradient(y0, y1, stops):
    """Fill rows y0..y1 with a vertical multi-stop gradient.

    stops: list of (position 0..1, color), sorted by position.
    """
    span = y1 - y0
    for y in range(y0, y1 + 1):
        t = (y - y0) / span if span else 0.0
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]
            p1, c1 = stops[i + 1]
            if t <= p1:
                f = 0.0 if p1 == p0 else (t - p0) / (p1 - p0)
                fill_run(y, 0, W - 1, lerp_color(c0, c1, max(0.0, min(1.0, f))))
                break
        else:
            fill_run(y, 0, W - 1, stops[-1][1])


def disc(cx, cy, r, color):
    """Solid filled disc."""
    r = int(r)
    for y in range(max(0, cy - r), min(H, cy + r + 1)):
        dy = y - cy
        half = int(math.sqrt(max(0, r * r - dy * dy)))
        fill_run(y, cx - half, cx + half, color)


def soft_disc(cx, cy, r, color, alpha_max):
    """Disc whose alpha fades quadratically from centre to edge."""
    r = int(r)
    if r <= 0 or alpha_max <= 0:
        return
    r2 = r * r
    for y in range(max(0, cy - r), min(H, cy + r + 1)):
        dy = y - cy
        half = int(math.sqrt(max(0, r2 - dy * dy)))
        for x in range(max(0, cx - half), min(W, cx + half + 1)):
            dx = x - cx
            d2 = dx * dx + dy * dy
            f = 1.0 - d2 / r2
            blend(x, y, color, int(alpha_max * f * f))


def soft_ellipse(cx, cy, rx, ry, color, alpha_max):
    """Soft horizontal ellipse, alpha fading to the rim."""
    for y in range(max(0, cy - ry), min(H, cy + ry + 1)):
        ny = (y - cy) / ry
        half = int(rx * math.sqrt(max(0.0, 1.0 - ny * ny)))
        for x in range(max(0, cx - half), min(W, cx + half + 1)):
            nx = (x - cx) / rx
            d2 = nx * nx + ny * ny
            if d2 < 1.0:
                f = 1.0 - d2
                blend(x, y, color, int(alpha_max * f * f))


def fill_poly(points, color):
    """Scanline fill of a simple polygon."""
    ys = [p[1] for p in points]
    y0 = max(0, min(ys))
    y1 = min(H - 1, max(ys))
    n = len(points)
    for y in range(y0, y1 + 1):
        xs = []
        for i in range(n):
            x0, yp0 = points[i]
            x1, yp1 = points[(i + 1) % n]
            if yp0 == yp1:
                continue
            if min(yp0, yp1) <= y < max(yp0, yp1):
                t = (y - yp0) / (yp1 - yp0)
                xs.append(x0 + t * (x1 - x0))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            fill_run(y, int(xs[i]), int(xs[i + 1]), color)


def line(x0, y0, x1, y1, color):
    """Thin line (DDA) for masts, birds and stair risers."""
    steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    for i in range(steps + 1):
        t = i / steps
        put(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), color)


def bird(x, y, s):
    """One small gull: two short strokes meeting at a point."""
    line(x - s, y + s // 2, x, y, DARK)
    line(x, y, x + s, y + s // 2, DARK)


# --- the letters of VELMARA, 7 columns x 9 rows each --------------------
# "X" is ink, "." is empty. Drawn large with a dark outline pass, then
# cream, so the name reads against the dusk sky.
LETTERS = {
    "V": [
        "X.....X",
        "X.....X",
        "X.....X",
        "X.....X",
        "X.....X",
        ".X...X.",
        ".X...X.",
        "..X.X..",
        "...X...",
    ],
    "E": [
        "XXXXXXX",
        "X......",
        "X......",
        "XXXXX..",
        "X......",
        "X......",
        "X......",
        "X......",
        "XXXXXXX",
    ],
    "L": [
        "X......",
        "X......",
        "X......",
        "X......",
        "X......",
        "X......",
        "X......",
        "X......",
        "XXXXXXX",
    ],
    "M": [
        "X.....X",
        "XX...XX",
        "X.X.X.X",
        "X..X..X",
        "X.....X",
        "X.....X",
        "X.....X",
        "X.....X",
        "X.....X",
    ],
    "A": [
        "...X...",
        "..X.X..",
        "..X.X..",
        ".X...X.",
        ".X...X.",
        "X.....X",
        "XXXXXXX",
        "X.....X",
        "X.....X",
    ],
    "R": [
        "XXXXX..",
        "X....X.",
        "X....X.",
        "XXXXX..",
        "X..X...",
        "X...X..",
        "X....X.",
        "X....X.",
        "X....X.",
    ],
}


def draw_name(word, x0, y0, cell):
    """Draw the place name across the upper third of the poster."""
    gap = 10
    advance = 7 * cell + gap
    # Outline pass: each ink cell drawn slightly enlarged in dark teal,
    # so the cream letters carry a readable edge against the sky.
    for k, ch in enumerate(word):
        grid = LETTERS[ch]
        ox = x0 + k * advance
        for r, row in enumerate(grid):
            for c, mark in enumerate(row):
                if mark == "X":
                    fill_rect(ox + c * cell - 4, y0 + r * cell - 4,
                              ox + c * cell + cell + 3,
                              y0 + r * cell + cell + 3, DARK)
    # Fill pass: the cream letterforms themselves.
    for k, ch in enumerate(word):
        grid = LETTERS[ch]
        ox = x0 + k * advance
        for r, row in enumerate(grid):
            for c, mark in enumerate(row):
                if mark == "X":
                    fill_rect(ox + c * cell, y0 + r * cell,
                              ox + c * cell + cell - 1,
                              y0 + r * cell + cell - 1, CREAM)


# --- the scene ------------------------------------------------------------

def paint_sky():
    vgradient(0, HORIZON, [
        (0.00, TEAL_DEEP),
        (0.55, TEAL_MID),
        (0.85, (196, 138, 74)),
        (1.00, AMBER_HORIZON),
    ])
    # Low amber sun, just below the name, with a wide soft glow that
    # washes up behind the letters.
    soft_disc(512, 400, 300, SUN_GLOW, 110)
    soft_disc(512, 400, 170, SUN_GLOW, 130)
    disc(512, 400, 58, SUN_CORE)
    soft_disc(512, 400, 58, (255, 230, 160), 60)
    # A few thin clouds, pale against the dusk.
    soft_ellipse(300, 300, 220, 16, MIST, 46)
    soft_ellipse(760, 330, 180, 13, MIST, 40)
    soft_ellipse(560, 500, 260, 14, (240, 200, 140), 52)
    soft_ellipse(180, 470, 150, 11, MIST, 36)
    # A few birds, high and small.
    bird(300, 330, 11)
    bird(352, 302, 9)
    bird(648, 282, 10)
    bird(706, 332, 8)
    bird(252, 420, 9)


def paint_sea(rng):
    vgradient(HORIZON, H - 1, [
        (0.00, SEA_TOP),
        (1.00, SEA_DEEP),
    ])
    # Bright pool of reflected sun right under the horizon.
    soft_ellipse(512, 604, 130, 8, SUN_GLOW, 100)
    # Shimmering horizontal bands of amber light down the sun's column,
    # widening and fading as the water comes nearer.
    y = HORIZON + 16
    while y < H - 8:
        depth = (y - HORIZON) / (H - HORIZON)
        half = int((46 + depth * 210) * (0.85 + 0.3 * rng.random()))
        height = rng.randint(3, 9)
        alpha = int(170 * (1.0 - depth) * (0.7 + 0.3 * rng.random()))
        jitter = rng.randint(-18, 18)
        blend_run(y, 512 - half + jitter, 512 + half + jitter,
                  SUN_GLOW, alpha)
        if height > 5:
            blend_run(y + 2, 512 - half + jitter, 512 + half + jitter,
                      SUN_CORE, alpha // 2)
        y += height + rng.randint(10, 24)
    # Thin mist lying over the water near the horizon.
    soft_ellipse(420, 614, 380, 12, MIST, 30)
    soft_ellipse(620, 642, 300, 10, MIST, 26)
    soft_ellipse(350, 672, 260, 9, MIST, 22)


def paint_headland():
    fill_poly([
        (0, 545), (120, 528), (215, 560), (258, 600),
        (215, 660), (140, 730), (40, 790), (0, 800),
    ], HEADLAND)
    # Three tiny warm windows on the headland: the town is inhabited.
    for wx, wy in ((96, 590), (150, 612), (60, 660)):
        soft_disc(wx, wy, 7, LANTERN, 70)
        disc(wx, wy, 2, LANTERN)


def paint_cliff():
    fill_poly([
        (1024, 452), (930, 478), (838, 545), (792, 600),
        (806, 720), (852, 880), (905, 1024), (1024, 1024),
    ], CLIFF)
    # Shade the seaward edge of the cliff so its face has depth.
    edge = [(838, 545), (792, 600), (806, 720), (852, 880), (905, 1024)]
    for i in range(len(edge) - 1):
        (ax, ay), (bx, by) = edge[i], edge[i + 1]
        for y in range(ay, by + 1):
            t = (y - ay) / (by - ay) if by != ay else 0.0
            ex = int(ax + (bx - ax) * t)
            blend_run(y, ex, ex + 22, CLIFF_SHADOW, 70)
    # Faint strata lines across the cliff face, so it reads as rock
    # rather than a flat wall.
    for sy in (640, 740, 840, 940):
        for i in range(len(edge) - 1):
            (ax, ay), (bx, by) = edge[i], edge[i + 1]
            if ay <= sy <= by:
                t = (sy - ay) / (by - ay) if by != ay else 0.0
                ex = int(ax + (bx - ax) * t)
                line(ex + 8, sy, ex + 150, sy + 16, CLIFF_SHADOW)
                break


def paint_stair_and_ribbon():
    """The Tide Stair climbs the cliff; beside it, the waterfall of
    light rises from the harbour and dissolves into the clouds."""
    # The rising waterfall of light: a soft golden ribbon that fades
    # as it climbs, drawn first so the stair sits over it.
    ax, ay, cx, cy, bx, by = 770, 662, 826, 566, 896, 496
    for i in range(48):
        t = i / 47
        x = round((1 - t) ** 2 * ax + 2 * (1 - t) * t * cx + t * t * bx)
        y = round((1 - t) ** 2 * ay + 2 * (1 - t) * t * cy + t * t * by)
        fade = 1.0 - t * 0.75
        soft_disc(x, y, int(21 - 12 * t), SUN_GLOW, int(150 * fade))
        soft_disc(x, y, int(8 - 4 * t), SUN_CORE, int(170 * fade))
    # The stair itself: a stone ramp from the harbour to the lighthouse,
    # with pale steps, darker risers, and warm lanterns along it.
    x0, y0, x1, y1 = 800, 655, 928, 508
    # Ramp band under the steps, a shade darker than the cliff.
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    px, py = -dy / length * 11, dx / length * 11
    fill_poly([
        (round(x0 + px), round(y0 + py)),
        (round(x1 + px), round(y1 + py)),
        (round(x1 - px), round(y1 - py)),
        (round(x0 - px), round(y0 - py)),
    ], (222, 205, 168))
    steps = 24
    for i in range(steps):
        t = i / (steps - 1)
        x = round(x0 + (x1 - x0) * t)
        y = round(y0 + (y1 - y0) * t)
        fill_rect(x - 9, y - 4, x + 9, y + 4, STONE)
        line(x - 9, y + 4, x + 9, y + 4, CLIFF_SHADOW)
        # A warm lantern every third step.
        if i % 3 == 1:
            soft_disc(x, y - 10, 12, LANTERN, 110)
            disc(x, y - 10, 4, LANTERN)


def paint_lighthouse():
    # Tower on the cliff top, cream with a dark cap, lamp glowing.
    fill_rect(922, 406, 958, 410, DARK)
    fill_rect(924, 410, 956, 505, CREAM)
    fill_rect(924, 410, 930, 505, CLIFF_SHADOW)
    fill_rect(924, 452, 956, 458, DARK)
    fill_rect(918, 398, 962, 410, DARK)
    fill_poly([(924, 398), (956, 398), (940, 382)], DARK)
    soft_disc(940, 388, 26, LANTERN, 130)
    fill_rect(930, 380, 950, 398, LANTERN)
    disc(940, 388, 4, (255, 240, 190))


def paint_boats():
    # Two small boats at anchor in the bay, one with a coral sail.
    def boat(cx, cy, s, sail):
        hw = int(20 * s)
        fill_poly([
            (cx - hw, cy), (cx + hw, cy),
            (cx + hw - 6, cy + int(11 * s)), (cx - hw + 6, cy + int(11 * s)),
        ], DARK)
        line(cx, cy, cx, cy - int(28 * s), DARK)
        if sail:
            fill_poly([
                (cx, cy - int(26 * s)), (cx, cy - 2),
                (cx + int(15 * s), cy - 2),
            ], CORAL)
        soft_disc(cx, cy - 2, 8, LANTERN, 80)
        disc(cx, cy - 2, 2, LANTERN)
        # A short smear of lantern light on the water below.
        blend_run(cy + int(14 * s), cx - 8, cx + 8, LANTERN, 60)
        blend_run(cy + int(18 * s), cx - 5, cx + 5, LANTERN, 40)

    boat(420, 730, 1.0, True)
    boat(620, 812, 0.7, False)


def paint_frame():
    # A quiet cream frame line, inset from the edge, marks it a poster.
    blend_rect(18, 18, W - 19, 21, CREAM, 90)
    blend_rect(18, H - 22, W - 19, H - 19, CREAM, 90)
    blend_rect(18, 18, 21, H - 19, CREAM, 90)
    blend_rect(W - 22, 18, W - 19, H - 19, CREAM, 90)


# --- PNG encoder (hand-rolled, deterministic) ----------------------------

def encode_png():
    """Encode the framebuffer as a PNG: Sub-filtered RGB scanlines."""
    raw = bytearray()
    stride = W * 3
    for y in range(H):
        row = buf[y * stride:(y + 1) * stride]
        raw.append(1)  # filter type 1: Sub
        raw.extend(row[:3])
        for i in range(3, stride):
            raw.append((row[i] - row[i - 3]) & 0xFF)
    compressed = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", compressed)
            + chunk(b"IEND", b""))


def main():
    rng = random.Random(SEED)
    paint_sky()
    paint_sea(rng)
    paint_headland()
    paint_cliff()
    paint_stair_and_ribbon()
    paint_lighthouse()
    paint_boats()
    # The name, large across the upper third, over the sun's glow.
    draw_name("VELMARA", 90, 100, 16)
    paint_frame()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "wb") as f:
        f.write(encode_png())
    os.chmod(OUT_PATH, 0o644)


if __name__ == "__main__":
    main()
