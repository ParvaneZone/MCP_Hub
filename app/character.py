"""Procedural mascot ("Jinx"): squash/stretch body, blinking eyes, lip-sync mouth, gesturing arms,
bobbing antenna. Drawn 2x supersampled into a small RGBA sprite; no external assets needed."""
import math

from PIL import Image, ImageDraw

SW, SH = 780, 720          # sprite size (final pixels)
SS = 2                     # supersampling
K = 0.84                   # design units (760x860) -> sprite pixels


def _mix(a, b, t):
    return tuple(int(x * (1 - t) + y * t) for x, y in zip(a, b))


def draw_character(accent, body, *, bounce=0.0, squash=0.0, mouth=0.0, blink=0.0, brow=0.0,
                   gaze=(0.0, 0.0), pupil=(25, 25, 60), arm_l=0.35, arm_r=0.35, antenna=0.0, glow=0.0, tilt=0.0, mood="normal"):
    """All inputs are plain floats. mouth/blink/brow/glow in 0..1; arm_* in radians (0=down)."""
    S = SS * K
    img = Image.new("RGBA", (SW * SS, SH * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def P(x, y):
        return (x * S, y * S)

    def box(x0, y0, x1, y1):
        return (x0 * S, y0 * S, x1 * S, y1 * S)

    dark = _mix(body, (10, 10, 25), 0.62)
    light = _mix(body, (255, 255, 255), 0.35)
    plate = (22, 22, 44)
    cx = SW / K / 2
    top = 300 + bounce - squash * 18
    bot = 770 + bounce * 0.2
    wid = 210 + squash * 22

    # shadow (own alpha layer so it stays soft)
    x0, y0, x1, y1 = [int(v) for v in box(cx - 190 + squash * 10, 770, cx + 190 - squash * 10, 822)]
    sh = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((0, 0, x1 - x0 - 1, y1 - y0 - 1), fill=(0, 0, 0, 80))
    img.alpha_composite(sh, (x0, y0))
    d = ImageDraw.Draw(img)

    # feet
    for fx in (-85, 85):
        d.ellipse(box(cx + fx - 52, bot - 22, cx + fx + 52, bot + 28), fill=dark)

    # antenna (behind body)
    tipx, tipy = cx + antenna * 46, top - 120 - abs(antenna) * 10
    d.line([P(cx, top + 10), P(tipx, tipy)], fill=dark, width=int(14 * S), joint="curve")
    if glow > 0.02:
        r = 26 + 34 * glow
        hx0, hy0, hx1, hy1 = [int(v) for v in box(tipx - r * 1.8, tipy - r * 1.8, tipx + r * 1.8, tipy + r * 1.8)]
        halo = Image.new("RGBA", (hx1 - hx0, hy1 - hy0), (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse((0, 0, hx1 - hx0 - 1, hy1 - hy0 - 1), fill=accent + (int(60 * glow),))
        img.alpha_composite(halo, (max(0, hx0), max(0, hy0)), (max(0, -hx0), max(0, -hy0)))
        d = ImageDraw.Draw(img)
    d.ellipse(box(tipx - 26, tipy - 26, tipx + 26, tipy + 26), fill=accent)
    d.ellipse(box(tipx - 10, tipy - 14, tipx + 2, tipy - 2), fill=_mix(accent, (255, 255, 255), 0.7))

    # arms: shoulder -> hand (angle from straight-down; positive = outward/up)
    for side, ang in ((-1, arm_l), (1, arm_r)):
        sx, sy = cx + side * (wid - 8), 520 + bounce * 0.6
        hx = sx + side * 200 * math.sin(ang)
        hy = sy + 200 * math.cos(ang)
        d.line([P(sx, sy), P(hx, hy)], fill=dark, width=int(48 * S))
        d.ellipse(box(sx - 24, sy - 24, sx + 24, sy + 24), fill=dark)
        d.ellipse(box(hx - 36, hy - 36, hx + 36, hy + 36), fill=light)

    # body bean
    d.rounded_rectangle(box(cx - wid, top, cx + wid, bot), radius=int(190 * S), fill=body)
    d.ellipse(box(cx - 120, 590 + bounce * 0.3, cx + 120, 750), fill=light)
    d.ellipse(box(cx - 170, top + 20, cx - 110, top + 50), fill=_mix(body, (255, 255, 255), 0.55))

    # face plate
    d.rounded_rectangle(box(cx - 170, top + 40, cx + 170, top + 270), radius=int(105 * S), fill=plate)

    # headphones = the mascot's signature
    band = _mix(accent, (255, 255, 255), 0.15)
    d.arc(box(cx - 212, top - 96, cx + 212, top + 296), 180, 360, fill=dark, width=int(20 * S))
    for sx in (-1, 1):
        ccx = cx + sx * (wid + 4)
        d.rounded_rectangle(box(ccx - 30, top + 92, ccx + 30, top + 206), radius=int(24 * S), fill=band)
        d.rounded_rectangle(box(ccx - 16, top + 108, ccx + 16, top + 190), radius=int(14 * S), fill=dark)

    # eyes
    gx, gy = gaze
    big = 1.22 if mood == "shock" else 1.0
    if mood == "shock":
        brow = max(brow, 1.2)
        mouth = max(mouth, 0.85)
    for ex in (-80, 80):
        ecx, ecy = cx + ex, top + 140
        eh = max(4, 54 * big * (1 - blink))
        d.ellipse(box(ecx - 44 * big, ecy - eh, ecx + 44 * big, ecy + eh), fill=(255, 255, 255))
        if blink < 0.7:
            pr = 22
            d.ellipse(box(ecx + gx * 14 - pr, ecy + gy * 10 - pr * (1 - blink),
                          ecx + gx * 14 + pr, ecy + gy * 10 + pr * (1 - blink)), fill=pupil)
            d.ellipse(box(ecx + gx * 14 - 8, ecy + gy * 10 - 14, ecx + gx * 14 + 4, ecy + gy * 10 - 2),
                      fill=(255, 255, 255))
        # eyebrows
        by = ecy - 80 - brow * 22
        d.line([P(ecx - 40, by + ex * 0.06 * brow + 6), P(ecx + 40, by - ex * 0.06 * brow + 6)],
               fill=_mix(body, (255, 255, 255), 0.45), width=int(13 * S))

    # cheeks + mouth
    for ex in (-122, 122):
        d.ellipse(box(cx + ex - 26, top + 205 + 0, cx + ex + 26, top + 235), fill=(255, 110, 140))
    my = top + 218
    mh = 6 + 44 * mouth
    mw = 36 + 16 * mouth
    d.rounded_rectangle(box(cx - mw, my - 6, cx + mw, my + mh), radius=int(min(mw, mh + 6) * S * 0.9),
                        fill=(255, 100, 120) if mouth > 0.12 else (255, 140, 160))
    if mood == "happy" and mouth < 0.3:
        d.arc(box(cx - 52, my - 34, cx + 52, my + 34), 20, 160, fill=(255, 100, 120), width=int(12 * S))
    if mouth > 0.35:
        d.ellipse(box(cx - mw * 0.55, my + mh * 0.5, cx + mw * 0.55, my + mh + 4), fill=(210, 50, 80))

    out = img.reduce(SS)
    if abs(tilt) > 0.05:
        out = out.rotate(tilt, resample=Image.BILINEAR, center=(SW // 2, SH - 40))
    return out
