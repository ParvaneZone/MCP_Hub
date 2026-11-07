"""Flat vector illustrations used as visual metaphors (drawn 2x, cached by the renderer)."""
import math

from PIL import Image, ImageDraw

AW, AH = 800, 560
INK = (34, 24, 58)
PAPER = (255, 255, 255)


def _mix(a, b, t):
    return tuple(int(x * (1 - t) + y * t) for x, y in zip(a, b))


class _Pen:
    def __init__(self):
        self.img = Image.new("RGBA", (AW * 2, AH * 2), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def p(self, *v):
        return [x * 2 for x in v]

    def rect(self, x0, y0, x1, y1, fill, r=0, outline=None, w=0):
        self.d.rounded_rectangle(self.p(x0, y0, x1, y1), radius=r * 2, fill=fill,
                                 outline=outline, width=w * 2)

    def ell(self, x0, y0, x1, y1, fill=None, outline=None, w=0):
        self.d.ellipse(self.p(x0, y0, x1, y1), fill=fill, outline=outline, width=w * 2)

    def poly(self, pts, fill):
        self.d.polygon([c * 2 for xy in pts for c in xy], fill=fill)

    def line(self, pts, fill, w):
        self.d.line([c * 2 for xy in pts for c in xy], fill=fill, width=int(w * 2), joint="curve")

    def done(self):
        return self.img.reduce(2)


def _building(pen, cx, base, s, acc, ph, mark=True):
    w, h = 250 * s, 400 * s
    x0, y0 = cx - w / 2, base - h
    pen.rect(x0 + 10, y0 + 12, x0 + w + 10, base + 12, (0, 0, 0, 60), 18 * s)
    pen.rect(x0, y0, x0 + w, base, PAPER, 18 * s)
    pen.rect(x0 + w * 0.34, y0 - 26 * s, x0 + w * 0.66, y0 + 4, _mix(PAPER, INK, 0.25), 6 * s)
    cols, rows = 4, 6
    for r in range(rows):
        for c in range(cols):
            wx = x0 + w * (0.1 + c * 0.2)
            wy = y0 + h * (0.07 + r * 0.14)
            ww, wh = w * 0.15, h * 0.09
            lit = ((r * 7 + c * 3 + ph * 5) % 5) < 2
            mine = mark and r == 3 and c == 1
            col = acc if (lit or mine) else _mix(PAPER, INK, 0.18)
            pen.rect(wx, wy, wx + ww, wy + wh, col, 4 * s)
            if mine:
                pen.rect(wx - 5 * s, wy - 5 * s, wx + ww + 5 * s, wy + wh + 5 * s, None, 7 * s,
                         outline=INK, w=max(2, int(5 * s)))
    pen.rect(x0 + w * 0.4, base - h * 0.12, x0 + w * 0.6, base, INK, 5 * s)


def _house(pen, cx, base, s, acc, ph):
    w, h = 330 * s, 200 * s
    x0, y0 = cx - w / 2, base - h
    pen.rect(x0 + 10, y0 + 12, x0 + w + 10, base + 12, (0, 0, 0, 60), 16 * s)
    pen.rect(x0 + w * 0.72, y0 - 110 * s, x0 + w * 0.86, y0 - 20 * s, _mix(acc, INK, 0.45), 4 * s)
    pen.rect(x0, y0, x0 + w, base, PAPER, 14 * s)
    pen.poly([(x0 - 26 * s, y0 + 6), (cx, y0 - 140 * s), (x0 + w + 26 * s, y0 + 6)], acc)
    glow = 0.0 if ph % 3 else 0.25
    for wx in (0.12, 0.62):
        pen.rect(x0 + w * wx, y0 + h * 0.2, x0 + w * (wx + 0.26), y0 + h * 0.62,
                 _mix((255, 214, 120), PAPER, glow), 8 * s)
        pen.line([(x0 + w * (wx + 0.13), y0 + h * 0.2), (x0 + w * (wx + 0.13), y0 + h * 0.62)], INK, 4 * s)
    pen.rect(x0 + w * 0.42, y0 + h * 0.4, x0 + w * 0.58, base, INK, 8 * s)


def _server(pen, cx, base, s, acc, ph):
    w = 380 * s
    for i in range(3):
        y1 = base - i * 126 * s
        y0 = y1 - 112 * s
        pen.rect(cx - w / 2 + 8, y0 + 10, cx + w / 2 + 8, y1 + 10, (0, 0, 0, 60), 16 * s)
        pen.rect(cx - w / 2, y0, cx + w / 2, y1, INK, 16 * s)
        pen.rect(cx - w / 2 + 14 * s, y0 + 14 * s, cx + w / 2 - 14 * s, y0 + 38 * s, _mix(INK, PAPER, 0.15), 6 * s)
        pen.rect(cx - w / 2 + 14 * s, y0 + 52 * s, cx + w / 2 - 14 * s, y0 + 76 * s, _mix(INK, PAPER, 0.15), 6 * s)
        for k in range(3):
            on = (ph + i + k) % 3 != 0
            pen.ell(cx + w / 2 - (40 + k * 30) * s, y0 + 88 * s, cx + w / 2 - (22 + k * 30) * s, y0 + 104 * s,
                    fill=acc if on else _mix(INK, PAPER, 0.3))


def _store(pen, cx, base, s, acc, ph):
    w, h = 340 * s, 230 * s
    x0, y0 = cx - w / 2, base - h
    pen.rect(x0 + 10, y0 + 12, x0 + w + 10, base + 12, (0, 0, 0, 60), 14 * s)
    pen.rect(x0, y0, x0 + w, base, PAPER, 12 * s)
    n = 6
    for i in range(n):
        pen.rect(x0 + w * i / n, y0 - 40 * s, x0 + w * (i + 1) / n, y0 + 34 * s,
                 acc if i % 2 == 0 else PAPER, 0)
    pen.rect(x0 + w * 0.08, y0 + h * 0.36, x0 + w * 0.5, base - 14 * s, _mix((200, 230, 255), PAPER, 0.3), 8 * s)
    pen.rect(x0 + w * 0.6, y0 + h * 0.36, x0 + w * 0.88, base, INK, 8 * s)


def _gauge(pen, cx, cy, s, acc, ph):
    r = 190 * s
    pen.d.pieslice(pen.p(cx - r, cy - r, cx + r, cy + r), 180, 360, fill=PAPER)
    pen.d.pieslice(pen.p(cx - r * 0.72, cy - r * 0.72, cx + r * 0.72, cy + r * 0.72), 180, 360, fill=_mix(INK, PAPER, 0.08))
    for i, col in enumerate(((255, 90, 90), (255, 200, 80), (110, 220, 140))):
        pen.d.arc(pen.p(cx - r * 0.86, cy - r * 0.86, cx + r * 0.86, cy + r * 0.86), 180 + i * 60, 240 + i * 60,
                  fill=col, width=int(16 * s * 2))
    a = math.radians(180 + 30 + ph * 24)
    pen.line([(cx, cy), (cx + r * 0.7 * math.cos(a), cy + r * 0.7 * math.sin(a))], acc, 12 * s)
    pen.ell(cx - 16 * s, cy - 16 * s, cx + 16 * s, cy + 16 * s, fill=acc)


def _check(pen, cx, cy, s, acc, ph, good=True):
    r = 150 * s
    col = (90, 210, 130) if good else (255, 95, 95)
    pen.ell(cx - r, cy - r, cx + r, cy + r, fill=col)
    if good:
        pen.line([(cx - r * 0.5, cy + 4 * s), (cx - r * 0.12, cy + r * 0.38), (cx + r * 0.52, cy - r * 0.32)], PAPER, 26 * s)
    else:
        pen.line([(cx - r * 0.42, cy - r * 0.42), (cx + r * 0.42, cy + r * 0.42)], PAPER, 26 * s)
        pen.line([(cx + r * 0.42, cy - r * 0.42), (cx - r * 0.42, cy + r * 0.42)], PAPER, 26 * s)


def _warning(pen, cx, cy, s, acc, ph):
    r = 190 * s
    pen.poly([(cx, cy - r), (cx + r * 1.05, cy + r * 0.8), (cx - r * 1.05, cy + r * 0.8)], (255, 200, 60))
    pen.rect(cx - 14 * s, cy - r * 0.4, cx + 14 * s, cy + r * 0.25, INK, 8 * s)
    pen.ell(cx - 16 * s, cy + r * 0.38, cx + 16 * s, cy + r * 0.38 + 32 * s, fill=INK)


def _globe(pen, cx, cy, s, acc, ph):
    r = 170 * s
    pen.ell(cx - r, cy - r, cx + r, cy + r, fill=_mix(acc, PAPER, 0.15))
    for k in (0.35, 0.7, 1.0):
        pen.ell(cx - r * k, cy - r, cx + r * k, cy + r, outline=INK, w=max(2, int(6 * s)))
    for dy in (-0.5, 0, 0.5):
        pen.line([(cx - r * math.sqrt(1 - dy * dy), cy + r * dy), (cx + r * math.sqrt(1 - dy * dy), cy + r * dy)], INK, 6 * s)


def make(visual, acc, ph):
    """-> RGBA image AW x AH for the named visual. Unknown -> None."""
    pen = _Pen()
    if visual == "building":
        _building(pen, 400, 520, 1.15, acc, ph)
    elif visual == "house":
        _house(pen, 400, 520, 1.25, acc, ph)
    elif visual == "server":
        _server(pen, 400, 520, 1.1, acc, ph)
    elif visual == "store":
        _store(pen, 400, 520, 1.25, acc, ph)
    elif visual == "gauge":
        _gauge(pen, 400, 440, 1.5, acc, ph)
    elif visual == "check":
        _check(pen, 400, 290, 1.4, acc, ph, True)
    elif visual == "cross":
        _check(pen, 400, 290, 1.4, acc, ph, False)
    elif visual == "warning":
        _warning(pen, 400, 290, 1.3, acc, ph)
    elif visual == "globe":
        _globe(pen, 400, 290, 1.4, acc, ph)
    elif visual == "compare":   # building (shared host) vs house (own server)
        _building(pen, 190, 500, 0.8, acc, ph, mark=True)
        _house(pen, 610, 500, 0.95, acc, ph)
        pen.ell(340, 220, 460, 340, fill=INK)
        pen.d.text(pen.p(400, 280), "VS", fill=PAPER, anchor="mm",
                   font=_vs_font())
    else:
        return None
    return pen.done()


_vsf = None


def _vs_font():
    global _vsf
    if _vsf is None:
        from . import textfx
        _vsf = textfx.font(84)
    return _vsf


VISUALS = ["building", "house", "server", "store", "gauge", "check", "cross", "warning", "globe", "compare"]
