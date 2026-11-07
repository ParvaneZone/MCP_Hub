"""Tiny synthesized sound-design kit (numpy only): whoosh, pop, boom, ding. All float32 mono @44.1k."""
import numpy as np

SR = 44100


def _env(n, attack=0.005, decay=6.0):
    t = np.arange(n) / SR
    return np.minimum(1, t / attack) * np.exp(-decay * t)


def whoosh(dur=0.5, seed=1):
    n = int(dur * SR)
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n).astype(np.float32)
    out = np.zeros(n, dtype=np.float32)
    y = 0.0
    for i in range(n):                         # one-pole low-pass with a rising cutoff = "swoosh"
        a = 0.02 + 0.5 * (i / n) ** 1.5
        y += a * (noise[i] - y)
        out[i] = y
    env = np.sin(np.pi * np.linspace(0, 1, n)) ** 1.5
    out = out * env
    return 0.9 * out / (np.abs(out).max() + 1e-6)


def pop(f0=500, f1=1100, dur=0.14):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f0 + (f1 - f0) * (t / dur)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 22)).astype(np.float32)


def boom(dur=0.9):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 110 * np.exp(-3 * t) + 38
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.003, 4.5)
    rng = np.random.default_rng(3)
    hit = rng.standard_normal(n) * _env(n, 0.001, 40) * 0.5
    out = tone + hit
    return (out / (np.abs(out).max() + 1e-6)).astype(np.float32)


def ding(dur=0.9):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = (np.sin(2 * np.pi * 1318 * t) + 0.6 * np.sin(2 * np.pi * 1760 * t)) * _env(n, 0.002, 5)
    return (out / (np.abs(out).max() + 1e-6)).astype(np.float32)


KINDS = {"whoosh": whoosh, "pop": pop, "boom": boom, "ding": ding}
_cache = {}


def mix_into(track, events):
    """events: [(time_sec, kind, volume)] -> adds in place."""
    for t, kind, vol in events:
        if kind not in _cache:
            _cache[kind] = KINDS[kind]()
        s = _cache[kind]
        a = int(t * SR)
        if a < 0 or a >= len(track):
            continue
        b = min(len(track), a + len(s))
        track[a:b] += vol * s[: b - a]
