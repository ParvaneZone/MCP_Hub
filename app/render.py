import colorsys
import glob
import math
import os
import random
import subprocess
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from . import art, character, sfx, textfx as T, tts
from .config import DATA_DIR, MAX_SECONDS

W, H = 1080, 1920
FPS = 30
FADE = 0.5

# (bg top, bg bottom, text, accent)
THEMES = {
    "navy": ((10, 25, 60), (30, 80, 160), (255, 255, 255), (120, 190, 255)),
    "sunset": ((60, 10, 50), (220, 90, 60), (255, 255, 255), (255, 220, 150)),
    "emerald": ((5, 40, 35), (20, 140, 110), (255, 255, 255), (170, 255, 220)),
    "dark": ((10, 10, 12), (45, 45, 58), (255, 255, 255), (255, 200, 60)),
    "light": ((245, 247, 250), (205, 222, 245), (20, 30, 50), (30, 100, 220)),
}


def _mix(a, b, t):
    return tuple(int(x * (1 - t) + y * t) for x, y in zip(a, b))


def _hue(c, deg):
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in c))
    r, g, b = colorsys.hls_to_rgb((h + deg / 360) % 1, l, s)
    return (int(r * 255), int(g * 255), int(b * 255))


def _clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def _back(x):  # easeOutBack: pops with a small overshoot
    x = _clamp(x)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _grad(c1, c2):
    return ImageOps.colorize(Image.linear_gradient("L").resize((W, H)), c1, c2)


def plan(slides):
    """Estimated seconds per slide when there is no narration."""
    out = []
    for s in slides:
        if s.get("seconds"):
            out.append(float(s["seconds"]))
        else:
            words = len((s.get("title") or "").split()) + len(s["text"].split())
            out.append(round(max(2.5, min(8.0, 1.5 + words * 0.4)), 1))
    return out


def _music():
    m = glob.glob(str(DATA_DIR / "music" / "*.*"))
    m = [x for x in m if x.lower().endswith((".mp3", ".m4a", ".wav", ".aac"))]
    return random.choice(m) if m else None


_FRAME_FN = None


def _run_frame(fi):
    return _FRAME_FN(fi)


# --------------------------------------------------------------------------- character reel
def make_character_video(slides, theme, handle, out_path, gender="female", narrate=True):
    c1, c2, fg, accent = THEMES[theme]
    rng = random.Random(7)
    scratch = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    cap_font = T.font(92)
    INTRO, LEAD, PAD = 0.3, 0.08, 0.18

    # ---- 1. narration + timeline
    scenes, t = [], 0.0
    sfx_ev = []
    est = plan(slides)
    any_audio = False
    for i, s in enumerate(slides):
        kind = s.get("kind") or ("hook" if i == 0 else "cta" if i == len(slides) - 1 and s.get("button") else "body")
        raw = s["text"].strip()
        toks = raw.split()
        kw = [x.startswith("*") or x.endswith("*") for x in toks]
        spoken = " ".join(x.strip("*") for x in toks)       # may contain vowel marks -> only for the voice
        text = T.strip_marks(spoken)                         # clean text for captions
        samples, wt = tts.synth(spoken, gender) if narrate else (None, [])
        lead = (INTRO if i == 0 else 0) + LEAD
        if samples is not None:
            any_audio = True
            adur = len(samples) / tts.SR
            dur = max(lead + adur + PAD, float(s.get("seconds") or 0))
        else:
            dur = est[i]
            adur = max(1.0, dur - lead - PAD)
        a0 = t + lead
        words = [(a0 + x, a0 + y, w) for x, y, w in tts.word_timings(text, wt, adur)]
        kwf = {k: f for k, f in enumerate(kw)} if len(kw) == len(words) else {}
        font_px = 120 if kind == "hook" else 92
        cfont = T.font(font_px)
        chunks, cur = [], []
        for k, (_, _, w) in enumerate(words):
            test = " ".join(x[2] for x in [words[j] for j in cur + [k]])
            if cur and (len(cur) >= (3 if kind == "hook" else 4) or T.width(scratch, test, cfont) > 860):
                chunks.append(cur)
                cur = []
            cur.append(k)
        if cur:
            chunks.append(cur)
        ch = []
        for ci, idxs in enumerate(chunks):
            st = words[idxs[0]][0]
            en = words[chunks[ci + 1][0]][0] if ci + 1 < len(chunks) else t + dur
            ch.append({"idx": idxs, "t0": st, "t1": en})
        hs = (0, 7, -7)[i % 3]            # tiny hue drift: stays on-brand but not static
        sc_c1, sc_c2 = _hue(c1, hs), _hue(c2, hs)
        scenes.append({"t0": t, "t1": t + dur, "words": words, "chunks": ch, "samples": samples, "a0": a0,
                       "title": (s.get("title") or "").strip(), "c1": sc_c1, "c2": sc_c2,
                       "accent": _hue(accent, hs), "kind": kind, "visual": s.get("visual"),
                       "button": (s.get("button") or "").strip(), "tagline": (s.get("tagline") or "").strip(),
                       "kw": kwf, "font": cfont, "font_px": font_px})
        # sound design
        if kind == "hook":
            sfx_ev.append((t + 0.02, "boom", 0.55))
        elif i > 0:
            sfx_ev.append((t - 0.04, "whoosh", 0.35))
        if s.get("visual") or kind == "cta":
            sfx_ev.append((t + 0.18, "pop", 0.3))
        if kind == "cta":
            sfx_ev.append((t + 0.5, "ding", 0.35))
        for k, (a, _, _) in enumerate(words):
            if kwf.get(k):
                sfx_ev.append((a, "pop", 0.22))
        t += dur
    total = t + 0.3
    if total > MAX_SECONDS:
        raise ValueError(f"total duration {total:.0f}s exceeds {MAX_SECONDS:.0f}s; shorten the slides")
    nframes = int(math.ceil(total * FPS))

    # ---- 2. audio track + lip-sync envelope
    track = np.zeros(int(total * tts.SR) + tts.SR, dtype=np.float32)
    for sc in scenes:
        if sc["samples"] is not None:
            a = int(sc["a0"] * tts.SR)
            track[a:a + len(sc["samples"])] += sc["samples"]
    env = tts.envelope(track, nframes) if any_audio else None   # lip-sync from the voice only
    sfx.mix_into(track, sfx_ev)
    music = _music()

    # ---- 3. per-frame renderer
    grads = {}

    def grad(i):
        if i not in grads:
            grads[i] = _grad(scenes[i]["c1"], scenes[i]["c2"])
        return grads[i]

    parts = [(rng.random() * W, rng.random() * (H + 300), 25 + rng.random() * 55,
              6 + rng.random() * 18, rng.random() * 6.28) for _ in range(26)]
    blinks, tb = [], 1.2
    while tb < total:
        blinks.append(tb)
        tb += 2.2 + rng.random() * 2.2

    def blink_at(tt):
        for b in blinks:
            if 0 <= tt - b < 0.16:
                return math.sin(math.pi * (tt - b) / 0.16)
        return 0.0

    def scene_index(tt):
        for i, sc in enumerate(scenes):
            if tt < sc["t1"]:
                return i
        return len(scenes) - 1

    fonts = {"title": T.font(64), "handle": T.font(38)}
    cap_cache, st_cache = {}, {}

    art_cache, card_cache = {}, {}

    def caption_layer(sc, tt, accent_c):
        cur = None
        for c in sc["chunks"]:
            if c["t0"] <= tt:
                cur = c
        if cur is None or tt < sc["words"][0][0] - 0.05:
            return None
        ws = [sc["words"][k] for k in cur["idx"]]
        act = tuple(a <= tt < b for a, b, _ in ws)
        key = (id(sc), cur["t0"], act)
        lay = cap_cache.get(key)
        if lay is None:
            fpx = sc["font_px"]
            r = fpx / 92
            f_norm = sc["font"]
            f_kw = T.font(int(fpx * 1.2))
            fs = [f_kw if sc["kw"].get(k) else f_norm for k in cur["idx"]]
            widths = [T.width(scratch, w[2], f) for w, f in zip(ws, fs)]
            gap = 30
            tw = sum(widths) + gap * (len(ws) - 1)
            rtl = any(T.has_rtl(w[2]) for w in ws)
            lay = Image.new("RGBA", (1040, 320), (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            base = 190
            cx0 = 520 + tw / 2 if rtl else 520 - tw / 2
            for k, ((a, b, w), wd, on, f) in enumerate(zip(ws, widths, act, fs)):
                cxw = cx0 - wd / 2 if rtl else cx0 + wd / 2
                cx0 = cx0 - wd - gap if rtl else cx0 + wd + gap
                iskw = f is f_kw
                if on:
                    d.rounded_rectangle((cxw - wd / 2 - 24, base - 100 * r * (1.12 if iskw else 1),
                                         cxw + wd / 2 + 24, base + 36 * r), radius=int(38 * r), fill=accent_c)
                    T.draw_text(d, (cxw, base), w, f, (25, 20, 45), bold=2)
                elif iskw:
                    T.draw_text(d, (cxw, base), w, f, accent_c, stroke=9, stroke_fill=(15, 10, 30), bold=3)
                else:
                    T.draw_text(d, (cxw, base), w, f, (255, 255, 255), stroke=7,
                                stroke_fill=(15, 10, 30), bold=2)
            if len(cap_cache) > 200:
                cap_cache.clear()
            cap_cache[key] = lay
        k = _back((tt - cur["t0"]) / (0.28 if sc["kind"] == "hook" else 0.22))
        if k < 0.999:
            s = (0.55 if sc["kind"] == "hook" else 0.8) + (0.45 if sc["kind"] == "hook" else 0.2) * k
            lay = lay.resize((max(1, int(lay.width * s)), max(1, int(lay.height * s))), Image.BILINEAR)
        return lay

    def sticker_layer(sc, tt, accent_c):
        if not sc["title"] or sc["kind"] != "body":
            return None
        k = _back((tt - sc["t0"] - 0.12) / 0.4)
        if k <= 0.01:
            return None
        lay = st_cache.get(id(sc))
        if lay is None:
            wd = T.width(scratch, sc["title"], fonts["title"])
            lay = Image.new("RGBA", (int(wd) + 140, 170), (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            d.rounded_rectangle((8, 20, lay.width - 8, 150), radius=60, fill=(0, 0, 0, 70))
            d.rounded_rectangle((0, 10, lay.width - 16, 140), radius=60, fill=accent_c)
            T.draw_text(d, ((lay.width - 16) / 2, 100), sc["title"], fonts["title"], (30, 20, 50), bold=1)
            st_cache[id(sc)] = lay
        lay = lay.resize((max(1, int(lay.width * k)), max(1, int(lay.height * k))), Image.BILINEAR)
        return lay.rotate(-3 + 2 * math.sin(tt * 2.1), resample=Image.BICUBIC, expand=True)

    def art_layer(sc, lt, acc):
        ph = int(lt * 5) % 6
        key = (sc["visual"], acc, ph)
        im = art_cache.get(key)
        if im is None:
            im = art.make(sc["visual"], acc, ph)
            art_cache[key] = im
        if im is None:
            return None
        k = _back((lt - 0.1) / 0.5)
        if k <= 0.01:
            return None
        return im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.BILINEAR)

    def cta_layers(sc, lt, acc):
        """brand card + pulsing button"""
        k = _back((lt - 0.1) / 0.5)
        if k <= 0.01:
            return None, None
        card = card_cache.get(id(sc))
        if card is None:
            card = Image.new("RGBA", (900, 470), (0, 0, 0, 0))
            d = ImageDraw.Draw(card)
            d.rounded_rectangle((12, 24, 888, 460), radius=64, fill=(0, 0, 0, 70))
            d.rounded_rectangle((0, 0, 876, 436), radius=64, fill=(255, 255, 255, 245), outline=acc, width=10)
            T.draw_text(d, (438, 140), sc["title"] or handle or "", T.font(112), (34, 24, 58), bold=2)
            if sc["tagline"]:
                T.draw_text(d, (438, 235), sc["tagline"], T.font(50), _mix((34, 24, 58), (255, 255, 255), 0.25))
            if handle:
                T.draw_text(d, (438, 335), handle, T.font(56), _mix(acc, (34, 24, 58), 0.45))
            card_cache[id(sc)] = card
        btn = None
        if sc["button"]:
            bw = int(T.width(scratch, sc["button"], T.font(58))) + 140
            btn = Image.new("RGBA", (bw, 130), (0, 0, 0, 0))
            d = ImageDraw.Draw(btn)
            d.rounded_rectangle((0, 8, bw - 1, 122), radius=57, fill=(34, 24, 58))
            d.rounded_rectangle((6, 4, bw - 7, 112), radius=54, fill=acc)
            T.draw_text(d, (bw / 2, 90), sc["button"], T.font(58), (34, 24, 58), bold=1)
            pk = 1 + 0.06 * math.sin(lt * 7)
            btn = btn.resize((int(btn.width * pk * k), int(btn.height * pk * k)), Image.BILINEAR)
        card = card.resize((max(1, int(card.width * k)), max(1, int(card.height * k))), Image.BILINEAR)
        return card, btn

    def frame(fi):
        tt = fi / FPS
        si = scene_index(tt)
        sc = scenes[si]
        lt = tt - sc["t0"]
        acc = sc["accent"]
        kind = sc["kind"]
        has_art = bool(sc["visual"]) or kind == "cta"
        # background (+ ripple from the character when the scene changes)
        if si > 0 and lt < 0.6:
            r = _back(lt / 0.6) * 1500
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).ellipse((540 - r, 900 - r, 540 + r, 900 + r), fill=255)
            bg = Image.composite(grad(si), grad(si - 1), mask)
        else:
            bg = grad(si).copy()
        d = ImageDraw.Draw(bg)
        for (px, py, sp, r, ph) in parts:
            y = (py - sp * tt) % (H + 300) - 150
            x = px + 30 * math.sin(tt * 0.6 + ph)
            col = _mix(_mix(sc["c1"], sc["c2"], y / H), acc, 0.16)
            d.ellipse((x - r, y - r, x + r, y + r), fill=col)
        # speech energy
        words = sc["words"]
        started = [w for w in words if w[0] <= tt]
        last_start = started[-1][0] if started else -9
        speaking = bool(started) and tt < words[-1][1] + 0.05
        if env is not None:
            e = float(env[min(fi, nframes - 1)])
        else:
            e = (0.45 + 0.45 * math.sin(tt * 14)) if speaking and any(a <= tt < b for a, b, _ in words) else 0.0
        beat = math.exp(-(tt - last_start) * 7) if last_start > -5 else 0.0
        # layout of the mascot per scene type
        if kind == "hook":
            cs, ccx, ctop, mood = 0.7, 540, 960, "shock"
        elif has_art:
            cs, ccx, ctop, mood = 0.48, 840, 925, ("happy" if kind == "cta" else "normal")
        else:
            cs, ccx, ctop, mood = 1.0, 540, 520, "normal"
        # pulse ring behind the mascot
        rr = (330 + 60 * e + 12 * math.sin(tt * 2)) * cs
        ccy = ctop + 340 * cs
        d.ellipse((ccx - rr, ccy - rr, ccx + rr, ccy + rr), outline=_mix(sc["c2"], acc, 0.22), width=8)
        d.ellipse((ccx - rr * 0.78, ccy - rr * 0.78, ccx + rr * 0.78, ccy + rr * 0.78),
                  fill=_mix(_mix(sc["c1"], sc["c2"], 0.5), acc, 0.08))
        # arms / gestures
        al = ar = 0.35
        tilt = 2.5 * math.sin(tt * 1.3)
        cur_k, cs0 = -1, -9
        for k, c in enumerate(sc["chunks"]):
            if c["t0"] <= tt:
                cur_k, cs0 = k, c["t0"]
        pulse = math.sin(math.pi * _clamp((tt - cs0) / 0.85)) ** 1.2 if cur_k >= 0 else 0.0
        if kind == "hook":
            al = ar = 2.3 + 0.18 * math.sin(tt * 9)
        elif has_art:
            al = 2.2 + 0.2 * math.sin(tt * 5) + 0.3 * pulse
        elif cur_k % 2 == 0:
            al += 1.9 * pulse; tilt += 2 * pulse
        else:
            ar += 1.9 * pulse; tilt -= 2 * pulse
        al += 0.06 * math.sin(tt * 2.3); ar += 0.06 * math.cos(tt * 2.1)
        hop = 60 * math.sin(math.pi * lt / 0.45) if (si > 0 and lt < 0.45) else 0
        sprite = character.draw_character(
            acc, _mix(acc, (255, 255, 255), 0.08), bounce=-16 * beat + 5 * math.sin(tt * 2.2) - hop,
            squash=0.5 * beat, mouth=_clamp(e * 1.15), blink=blink_at(tt), brow=0.6 * beat + 0.3 * e,
            gaze=(0.6 * math.sin(tt * 0.7), 0.3 * math.cos(tt * 0.5) + 0.2),
            pupil=_mix(acc, (0, 0, 20), 0.6), arm_l=al, arm_r=ar,
            antenna=0.6 * math.sin(tt * 3.1) + 0.4 * beat, glow=_clamp(e), tilt=tilt, mood=mood)
        pop = _back(tt / 0.6) if tt < 0.6 else 1.0
        z = cs * pop
        if abs(z - 1) > 0.001:
            sprite = sprite.resize((max(1, int(sprite.width * z)), max(1, int(sprite.height * z))), Image.BILINEAR)
        bg.paste(sprite, (int(ccx - sprite.width / 2), int(ctop + (character.SH * cs - sprite.height))), sprite)
        # illustration / brand card
        if kind == "cta":
            card, btn = cta_layers(sc, lt, acc)
            if card is not None:
                bg.paste(card, (500 - card.width // 2, 600 - card.height // 2), card)
                if btn is not None:
                    bg.paste(btn, (500 - btn.width // 2, 600 + 262 - btn.height // 2), btn)
        elif sc["visual"]:
            al_ = art_layer(sc, lt, acc)
            if al_ is not None:
                bob = 8 * math.sin(lt * 2.4)
                bg.paste(al_, (500 - al_.width // 2, int(700 + bob - al_.height // 2)), al_)
        # sticker + caption
        st = sticker_layer(sc, tt, acc)
        if st is not None:
            bg.paste(st, (540 - st.width // 2, 340 - st.height // 2), st)
        cap = caption_layer(sc, tt, acc)
        if cap is not None:
            cy = 800 if kind == "hook" else 1340
            sx = sy = 0
            if kind == "hook" and lt < 0.5:
                dec = (0.5 - lt) / 0.5
                sx, sy = int(14 * dec * math.sin(lt * 90)), int(10 * dec * math.cos(lt * 110))
            bg.paste(cap, (540 - cap.width // 2 + sx, cy - cap.height // 2 + sy), cap)
        # progress + handle
        d = ImageDraw.Draw(bg)
        d.rounded_rectangle((160, 262, 920, 270), radius=4, fill=_mix(sc["c1"], fg, 0.25))
        d.rounded_rectangle((160, 262, 160 + 760 * tt / total, 270), radius=4, fill=acc)
        if handle and kind != "cta":
            T.draw_text(d, (540, 1585), handle, fonts["handle"], _mix(sc["c2"], fg, 0.7), anchor="ms")
        if kind == "hook" and lt < 0.14:           # impact flash
            bg = Image.blend(bg, Image.new("RGB", (W, H), (255, 255, 255)), 0.55 * (1 - lt / 0.14))
        return bg.tobytes()

    # ---- 4. encode
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "voice.wav")
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(tts.SR)
            wf.writeframes((np.clip(track, -1, 1) * 32767).astype(np.int16).tobytes())
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", wav]
        if music:
            cmd += ["-stream_loop", "-1", "-i", music]
            vol = 0.12 if any_audio else 0.35
            af = (f"[2:a]volume={vol},afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5[m];"
                  f"[1:a][m]amix=inputs=2:duration=first:normalize=0[aout]")
        else:
            af = "[1:a]anull[aout]"
        cmd += ["-filter_complex", af, "-map", "0:v", "-map", "[aout]", "-t", f"{total:.3f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_path)]
        errf = open(os.path.join(tmp, "err.txt"), "w+")
        pr = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errf)
        global _FRAME_FN
        _FRAME_FN = frame
        workers = int(os.environ.get("RENDER_WORKERS", min(4, os.cpu_count() or 1)))
        try:
            if workers > 1:
                import multiprocessing as mp
                with mp.get_context("fork").Pool(workers) as pool:  # fork: workers inherit `frame`
                    for fb in pool.imap(_run_frame, range(nframes), chunksize=6):
                        pr.stdin.write(fb)
            else:
                for fi in range(nframes):
                    pr.stdin.write(frame(fi))
            pr.stdin.close()
            pr.wait()
        except BrokenPipeError:
            pass
        if pr.returncode != 0:
            errf.seek(0)
            raise RuntimeError("ffmpeg failed: " + errf.read()[-500:])
    return total


# --------------------------------------------------------------------------- classic slides (fixed text)
def _layout(draw, text, maxw, maxh, start, minsize):
    size = start
    while True:
        f = T.font(size)
        lines = T.wrap(draw, text, f, maxw)
        lh = int(size * 1.55)
        if len(lines) * lh <= maxh or size <= minsize:
            return f, lines, lh
        size -= 4


def render_slide(slide, idx, n, theme, handle, path):
    c1, c2, fg, accent = THEMES[theme]
    img = _grad(c1, c2)
    d = ImageDraw.Draw(img)
    maxw = W - 180
    blocks = []
    title = (slide.get("title") or "").strip()
    if title:
        f, lines, lh = _layout(d, title, maxw, 300, 70, 40)
        blocks.append((f, lines, lh, accent, 40))
    f, lines, lh = _layout(d, slide["text"].strip(), maxw, 1000 if title else 1200, 84, 44)
    blocks.append((f, lines, lh, fg, 0))
    total = sum(len(b[1]) * b[2] + b[4] for b in blocks)
    y = 260 + max(0, (1240 - total) // 2)
    for f, lines, lh, col, gap in blocks:
        for line in lines:
            T.draw_text(d, (W // 2, y), line, f, col, anchor="mt")
            y += lh
        y += gap
    r, gap_x = 9, 34
    x0 = W // 2 - (n - 1) * gap_x // 2
    for i in range(n):
        col = accent if i == idx else _mix(c1, fg, 0.3)
        cx = x0 + i * gap_x
        d.ellipse((cx - r, 1560 - r, cx + r, 1560 + r), fill=col)
    if handle:
        T.draw_text(d, (W // 2, 1610), handle, T.font(40), _mix(c2, fg, 0.7), anchor="mt")
    img.save(path, "PNG")


def make_video(slides, durations, theme, handle, out_path):
    n = len(slides)
    fade = min(FADE, min(durations) / 2)
    total = sum(durations)
    with tempfile.TemporaryDirectory() as tmp:
        imgs = []
        for i, s in enumerate(slides):
            p = os.path.join(tmp, f"s{i}.png")
            render_slide(s, i, n, theme, handle, p)
            imgs.append(p)
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for i, p in enumerate(imgs):
            length = durations[i] + (fade if i < n - 1 else 0)
            cmd += ["-loop", "1", "-framerate", "30", "-t", f"{length:.3f}", "-i", p]
        music = _music()
        if music:
            cmd += ["-stream_loop", "-1", "-i", music]
            audio = f"[{n}:a]volume=0.35,afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5[aout]"
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            audio = f"[{n}:a]anull[aout]"
        fl = [f"[{i}:v]fps=30,format=yuv420p,setsar=1[v{i}]" for i in range(n)]
        prev, off = "v0", 0.0
        for i in range(1, n):
            off += durations[i - 1]
            fl.append(f"[{prev}][v{i}]xfade=transition=fade:duration={fade:.3f}:offset={off:.3f}[x{i}]")
            prev = f"x{i}"
        fl.append(audio)
        cmd += ["-filter_complex", ";".join(fl), "-map", f"[{prev}]", "-map", "[aout]",
                "-t", f"{total:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(out_path)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg failed: " + r.stderr[-500:])
    return total
