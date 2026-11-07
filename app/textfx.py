"""Persian/RTL-safe text drawing.

Root cause of the old "reversed & broken" Persian text: the code reshaped + bidi-reordered the
string by hand and then handed it to Pillow. When Pillow has libraqm (almost every modern wheel),
raqm does shaping + bidi itself, so the text got reordered a second time -> mirrored letters.

Rule used here: if raqm is available -> pass the RAW logical string (direction=rtl, language=fa);
otherwise (BASIC layout) -> reshape + get_display manually. Never both.
"""
import glob
from functools import lru_cache

from PIL import ImageFont, features

from .config import FONT_DIR

HAS_RAQM = features.check("raqm")
_LAYOUT = ImageFont.Layout.RAQM if HAS_RAQM else ImageFont.Layout.BASIC

_reshaper = None
_get_display = None
if not HAS_RAQM:
    import arabic_reshaper
    from bidi.algorithm import get_display as _get_display
    _reshaper = arabic_reshaper.ArabicReshaper(configuration={"support_ligatures": True})


def has_rtl(s):
    return any("\u0590" <= c <= "\u08ff" or "\ufb50" <= c <= "\ufeff" for c in s)


_MARKS = "".join(chr(c) for c in list(range(0x064B, 0x0653)) + [0x0670, 0x0640])


def strip_marks(s):
    """Remove vowel marks (harakat) + tatweel: they are for the TTS voice, not for the on-screen caption."""
    return "".join(c for c in s if c not in _MARKS)


def prep(s):
    """-> (string to hand to Pillow, extra kwargs for textlength/text)."""
    if not has_rtl(s):
        return s, {}
    if HAS_RAQM:
        return s, {"direction": "rtl", "language": "fa"}
    return _get_display(_reshaper.reshape(s)), {}


@lru_cache(maxsize=64)
def font(size):
    files = sorted(glob.glob(str(FONT_DIR / "*.ttf")) + glob.glob(str(FONT_DIR / "*.otf")))
    pref = [f for f in files if "vazir" in f.lower()] or [f for f in files if "dirooz" in f.lower()] or files
    pref.sort(key=lambda f: "bold" not in f.lower())
    for p in pref + ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(p, size, layout_engine=_LAYOUT)
        except OSError:
            continue
    return ImageFont.load_default()


def width(draw, s, f):
    t, kw = prep(s)
    return draw.textlength(t, font=f, **kw)


def draw_text(draw, xy, s, f, fill, anchor="ms", stroke=0, stroke_fill=None, bold=0):
    """Draw one run. `bold` fakes a heavier weight (font is single-weight) with a same-colour stroke."""
    t, kw = prep(s)
    if stroke:
        draw.text(xy, t, font=f, fill=fill, anchor=anchor, stroke_width=stroke + bold,
                  stroke_fill=stroke_fill or (0, 0, 0), **kw)
    draw.text(xy, t, font=f, fill=fill, anchor=anchor, stroke_width=bold, stroke_fill=fill, **kw)


def wrap(draw, text, f, maxw):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            test = f"{cur} {word}".strip()
            if width(draw, test, f) <= maxw or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines
