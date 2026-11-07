import asyncio
import logging
import os
import sys
import threading
import uuid
from typing import Literal, Optional

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.responses import PlainTextResponse

from . import config, db, render, telegram_bot as bot
from .uploader import BASE as UPLOAD_BASE

log = logging.getLogger("server")

mcp = FastMCP(
    "reels",
    instructions=(
        "Creates Instagram Reels as a talking-mascot explainer (mascot with headphones, illustrations, "
        "kinetic captions, sound design). create_reel renders in the background and sends a preview to the "
        "owner's Telegram; nothing is published until the owner taps approve. STORY RULES: 6-8 short slides "
        "(2-4 s each, max ~12 words, one spoken sentence). Slide 1 = kind hook: a shocking/curious claim. "
        "Body slides: pick a `visual` metaphor (building/house/server/store/gauge/check/cross/warning/globe/"
        "compare) for most of them and a 1-3 word `title` sticker. Wrap the 1-2 key words of a line in *stars* "
        "to get big coloured captions. Last slide = kind cta: title=brand name, tagline, button text. "
        "slide.text is spoken: write it with full Persian vowel marks (fatha, kasra, damma, sukun); captions "
        "strip them. Never put a brand name in the spoken text if it sounds like an offensive word when read "
        "aloud; show it via title only. Write the caption with hashtags. Persian (RTL) is supported."
    ),
    host="0.0.0.0",
    port=config.LISTEN_PORT,
    stateless_http=True,
    json_response=True,
    streamable_http_path=f"/{config.MCP_SECRET or 'unset'}/mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


class Slide(BaseModel):
    text: str = Field(description="Main text of the slide (short).")
    title: Optional[str] = Field(None, description="Optional small heading above the text.")
    kind: Optional[Literal["hook", "body", "cta"]] = Field(
        None, description="hook = shocking opening line (huge text, mascot in shock); body = normal; "
                          "cta = final brand card. Default: first slide is hook, last is cta only if `button` is set.")
    visual: Optional[Literal["building", "house", "server", "store", "gauge", "check", "cross",
                             "warning", "globe", "compare"]] = Field(
        None, description="Illustration shown as a visual metaphor while this line is spoken.")
    button: Optional[str] = Field(None, description="cta only: call-to-action button text, e.g. 'message us'.")
    tagline: Optional[str] = Field(None, description="cta only: one short line under the brand name (title).")
    seconds: Optional[float] = Field(None, ge=1.5, le=15,
                                     description="Display time; omitted = estimated from text length.")


Theme = Literal["navy", "sunset", "emerald", "dark", "light"]


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return PlainTextResponse("ok")


_tasks = set()


def _handle_of(handle):
    return handle if handle is not None else config.DEFAULT_HANDLE


async def _render_job(job_id, data, theme, handle, gender, style, caption, out):
    try:
        if style == "classic":
            durations = render.plan(data)
            secs = await asyncio.to_thread(render.make_video, data, durations, theme, handle, out)
        else:
            secs = await asyncio.to_thread(render.make_character_video, data, theme, handle, out,
                                           gender, style != "silent")
        db.update(job_id, status="pending")
        mid = await asyncio.to_thread(bot.send_preview, job_id, caption, out, secs)
        db.update(job_id, tg_message_id=mid)
    except Exception as e:
        log.exception("render job %s failed", job_id)
        db.update(job_id, status="failed", detail=str(e)[:300])
        try:
            await asyncio.to_thread(bot.send, f"\u274c \u0633\u0627\u062e\u062a \u0631\u06cc\u0644 #{job_id} \u0646\u0627\u0645\u0648\u0641\u0642 \u0628\u0648\u062f: {str(e)[:300]}")
        except Exception:
            pass


@mcp.tool()
async def create_reel(slides: list[Slide], caption: str, theme: Theme = "sunset",
                      handle: Optional[str] = None,
                      voice: Literal["female", "male"] = "female",
                      style: Literal["character", "silent", "classic"] = "character") -> dict:
    """Render a vertical Reel in the background and send it to the owner's Telegram for approval.
    style=character (default): animated mascot narrates each slide with TTS + karaoke captions.
    style=silent: same animation without voice. style=classic: old static text slides.
    Returns immediately with status "rendering" (takes ~1-3 min); use reel_status to follow it.
    Publishing to Instagram happens only after the owner approves in Telegram."""
    if not 1 <= len(slides) <= 15:
        raise ValueError("slides must be between 1 and 15")
    if not caption.strip() or len(caption) > 2200:
        raise ValueError("caption must be 1..2200 characters")
    data = [s.model_dump() for s in slides]
    est = sum(render.plan(data))
    if est > config.MAX_SECONDS * 1.6:
        raise ValueError("too much text for one reel; shorten the slides")

    job_id = uuid.uuid4().hex[:8]
    out = config.DATA_DIR / "videos" / f"{job_id}.mp4"
    db.create(job_id, caption, str(out), theme)
    db.update(job_id, status="rendering")
    task = asyncio.create_task(_render_job(job_id, data, theme, _handle_of(handle), voice, style, caption, out))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"job_id": job_id, "status": "rendering",
            "message": "Rendering started. The preview will arrive in Telegram in a minute or two; "
                       "it is published only after the owner approves."}


@mcp.tool()
async def reel_status(job_id: str) -> dict:
    """Status of a reel: rendering, pending (waiting for approval), uploading, published, failed, rejected, expired."""
    j = db.get(job_id)
    if not j:
        raise ValueError("unknown job_id")
    return {k: j[k] for k in ("id", "status", "url", "detail")}


@mcp.tool()
async def list_reels(limit: int = 10) -> list[dict]:
    """Most recent reels and their statuses."""
    return [{"id": r["id"], "status": r["status"], "caption": (r["caption"] or "")[:60],
             "url": r["url"]} for r in db.recent(max(1, min(limit, 30)))]


@mcp.tool()
async def cancel_reel(job_id: str) -> dict:
    """Cancel a reel that is still waiting for approval."""
    if db.claim(job_id, "pending", "cancelled"):
        db.remove_video(job_id)
        return {"id": job_id, "status": "cancelled"}
    return {"id": job_id, "status": "not_cancellable"}


@mcp.tool()
async def upload_limits() -> list[dict]:
    """Check every configured upload-post API key (in failover order): validity, plan and rate-limit headers."""
    out = []
    async with httpx.AsyncClient(timeout=20) as c:
        for i, key in enumerate(config.UPLOADPOST_API_KEYS, 1):
            item = {"key": f"#{i} ...{key[-4:]}"}
            try:
                r = await c.get(f"{UPLOAD_BASE}/uploadposts/me", headers={"Authorization": f"Apikey {key}"})
                item["http"] = r.status_code
                try:
                    item["account"] = r.json()
                except Exception:
                    item["account"] = r.text[:200]
                item["limits"] = {k: v for k, v in r.headers.items()
                                  if "limit" in k.lower() or "remaining" in k.lower() or k.lower() == "retry-after"}
            except httpx.HTTPError as e:
                item["error"] = str(e)
            out.append(item)
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    miss = config.missing()
    if miss:
        sys.exit("Missing env: " + ", ".join(miss) + " (run ./install.sh)")
    db.init()
    threading.Thread(target=bot.run, daemon=True, name="telegram").start()
    log.info("MCP endpoint path: /<MCP_SECRET>/mcp on port %s", config.LISTEN_PORT)
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=config.LISTEN_PORT,
                log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
