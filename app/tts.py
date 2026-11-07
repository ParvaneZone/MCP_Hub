"""Narration: edge-tts (free neural voices, needs internet) + audio helpers.
Every failure degrades to silent/estimated timing instead of killing the render."""
import asyncio
import logging
import os
import subprocess
import tempfile

import numpy as np

from .textfx import has_rtl

log = logging.getLogger("tts")
SR = 44100
FPS = 30

VOICES = {
    ("fa", "female"): os.environ.get("TTS_VOICE_FA_F", "fa-IR-DilaraNeural"),
    ("fa", "male"): os.environ.get("TTS_VOICE_FA_M", "fa-IR-FaridNeural"),
    ("en", "female"): "en-US-AriaNeural",
    ("en", "male"): "en-US-AndrewNeural",
}
RATE = os.environ.get("TTS_RATE", "-3%")
PITCH = os.environ.get("TTS_PITCH", "+0Hz")

# Persian TTS mangles Latin acronyms -> speak them phonetically (captions keep the original text).
PRON = {
    "VPN": "وی‌پی‌ان", "SSD": "اس‌اس‌دی", "CPU": "سی‌پی‌یو", "RAM": "رم", "PHP": "پی‌اچ‌پی",
    "DNS": "دی‌ان‌اس", "IP": "آی‌پی", "SSL": "اس‌اس‌ال", "HTTPS": "اچ‌تی‌تی‌پی‌اس", "cPanel": "سی‌پنل",
    "CDN": "سی‌دی‌ان", "WordPress": "وردپرس", "MySQL": "مای‌اس‌کیو‌ال", "Telegram": "تلگرام",
    "Instagram": "اینستاگرام", "WiFi": "وای‌فای", "Wi-Fi": "وای‌فای", "ping": "پینگ", "Ping": "پینگ",
    "NVMe": "ان‌وی‌می", "LiteSpeed": "لایت‌اسپید", "Apache": "آپاچی", "Nginx": "انجین‌ایکس",
    "backup": "بک‌آپ", "Backup": "بک‌آپ", "cache": "کش", "Cache": "کش", "PDF": "پی‌دی‌اف", "AI": "ای‌آی",
}


def speakable(text):
    import re
    for k, v in sorted(PRON.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<![A-Za-z]){re.escape(k)}(?![A-Za-z])", v, text)
    return text


async def _stream(text, voice, path):
    import edge_tts
    text = speakable(text) if has_rtl(text) else text
    try:
        comm = edge_tts.Communicate(text, voice, rate=RATE, pitch=PITCH, boundary="WordBoundary")
    except TypeError:  # older edge-tts
        comm = edge_tts.Communicate(text, voice, rate=RATE, pitch=PITCH)
    words = []
    with open(path, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
    return words


def _decode(path):
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "s16le", "-ar", str(SR),
                        "-ac", "1", "-"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("decode failed")
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _fake(text, path):
    """Test hook (REELS_FAKE_TTS=1): speech-like modulated tone so lip-sync can be tested offline."""
    dur = max(1.5, len(text.split()) * 0.38)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"aevalsrc='0.4*sin(2*PI*180*t)*abs(sin(2*PI*3.2*t))':d={dur}:s={SR}", path], check=True)
    return []


def _http_mp3(url, headers, body, path):
    import json
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r, open(path, "wb") as f:
        f.write(r.read())


def _openai(text, gender, path):
    key = os.environ["OPENAI_API_KEY"]
    voice = os.environ.get("OPENAI_VOICE_" + ("F" if gender == "female" else "M"),
                           "nova" if gender == "female" else "onyx")
    _http_mp3("https://api.openai.com/v1/audio/speech", {"Authorization": f"Bearer {key}"}, {
        "model": os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"), "voice": voice,
        "input": speakable(text) if has_rtl(text) else text, "response_format": "mp3",
        "instructions": "Speak natural, clear, conversational Persian (Farsi) with a Tehran accent, like an "
                        "energetic social-media explainer. Pronounce every word clearly, moderate pace, short pauses at punctuation."},
        path)


def _eleven(text, gender, path):
    key = os.environ["ELEVENLABS_API_KEY"]
    vid = os.environ.get("ELEVEN_VOICE_" + ("F" if gender == "female" else "M"),
                         "EXAVITQu4vr4xnSDxMzb" if gender == "female" else "pNInz6obpgDQGcFmaJgB")
    _http_mp3(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=mp3_44100_128",
              {"xi-api-key": key}, {"text": text, "model_id": os.environ.get("ELEVEN_MODEL", "eleven_multilingual_v2"),
                                    "language_code": "fa" if has_rtl(text) else "en",
                                    "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.3}}, path)


PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/fa/fa_IR"


def _piper_model():
    """Download the Persian Piper voice once into DATA_DIR/piper (persisted volume)."""
    import urllib.request
    from .config import DATA_DIR
    name = os.environ.get("PIPER_VOICE", "amir")        # amir | gyro
    d = DATA_DIR / "piper"
    d.mkdir(parents=True, exist_ok=True)
    model = d / f"fa_IR-{name}-medium.onnx"
    for f in (model, model.with_suffix(".onnx.json")):
        if not f.exists() or f.stat().st_size < 1000:
            url = f"{PIPER_BASE}/{name}/medium/{f.name}"
            log.info("downloading Piper voice %s", url)
            urllib.request.urlretrieve(url, str(f) + ".part")
            os.replace(str(f) + ".part", f)
    return str(model)


def _piper(text, gender, path):
    import sys
    t = speakable(text) if has_rtl(text) else text
    cmd = [sys.executable, "-m", "piper", "-m", _piper_model(), "-f", path,
           "--length-scale", os.environ.get("PIPER_LENGTH", "1.05"),
           "--sentence-silence", os.environ.get("PIPER_PAUSE", "0.25")]
    r = subprocess.run(cmd, input=t.encode("utf-8"), capture_output=True, timeout=180)
    if r.returncode != 0 or not os.path.exists(path):
        raise RuntimeError("piper failed: " + r.stderr.decode(errors="ignore")[-300:])


def _gtts(text, gender, path):
    from gtts import gTTS
    t = speakable(text) if has_rtl(text) else text
    gTTS(t, lang="fa" if has_rtl(text) else "en", slow=False).save(path)


def synth(text, gender="female"):
    """-> (samples float32 mono @SR or None, [(start,end,word)] relative to audio start).
    TTS_PROVIDER = edge (default, free) | piper (free, offline) | gtts (free) | openai | elevenlabs. A failing provider falls back to edge, then silence."""
    prov = os.environ.get("TTS_PROVIDER", "edge").lower()
    if prov in ("openai", "elevenlabs", "gtts", "piper") and not os.environ.get("REELS_FAKE_TTS"):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "v.mp3")
            try:
                {"openai": _openai, "elevenlabs": _eleven, "gtts": _gtts, "piper": _piper}[prov](text, gender if gender in ("female", "male") else "female", p)
                return _decode(p), []
            except Exception as e:
                log.warning("%s TTS failed (%s) -> falling back to edge", prov, e)
    lang = "fa" if has_rtl(text) else "en"
    voice = VOICES[(lang, gender if gender in ("female", "male") else "female")]
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "v.mp3")
        try:
            if os.environ.get("REELS_FAKE_TTS"):
                words = _fake(text, p)
            else:
                words = asyncio.run(_stream(text, voice, p))
            return _decode(p), words
        except Exception as e:
            log.warning("TTS failed (%s) -> silent scene", e)
            return None, []


def word_timings(text, words_tts, dur):
    """Map to text.split(); use engine boundaries if counts match, else spread by char length."""
    ws = text.split()
    if words_tts and len(words_tts) == len(ws):
        return [(a, max(b, a + 0.08), w) for (a, b, _), w in zip(words_tts, ws)]
    weights = [max(2, len(w)) + 1.5 for w in ws]
    tot = sum(weights)
    out, t = [], 0.0
    for w, wt in zip(ws, weights):
        d = dur * wt / tot
        out.append((t, t + d, w))
        t += d
    return out


def envelope(samples, total_frames):
    """Per-video-frame mouth energy 0..1 from the full audio track."""
    hop = SR // FPS
    n = min(total_frames, len(samples) // hop)
    if n <= 0:
        return np.zeros(total_frames, dtype=np.float32)
    x = samples[: n * hop].reshape(n, hop)
    rms = np.sqrt((x ** 2).mean(axis=1))
    ref = np.percentile(rms[rms > 1e-4], 90) if (rms > 1e-4).any() else 1.0
    e = np.clip(rms / max(ref, 1e-4), 0, 1)
    sm = np.convolve(e, np.array([0.25, 0.5, 0.25]), mode="same")
    out = np.zeros(total_frames, dtype=np.float32)
    out[:n] = sm
    return out
