import logging
import time

import httpx

from . import db
from .config import UPLOADPOST_API_KEY, UPLOADPOST_USER

log = logging.getLogger("uploader")
BASE = "https://api.upload-post.com/api"


class UploadError(Exception):
    pass


def _norm(results):
    """Normalise sync (dict) and status (list) result shapes."""
    items = []
    if isinstance(results, dict):
        for p, r in results.items():
            r = r or {}
            items.append((p, r))
    elif isinstance(results, list):
        for r in results:
            items.append((r.get("platform", "?"), r))
    return items


def _send(job, rid):
    headers = {"Authorization": f"Apikey {UPLOADPOST_API_KEY}", "Idempotency-Key": rid}
    data = {
        "user": UPLOADPOST_USER,
        "platform[]": "instagram",
        "title": job["caption"],
        "media_type": "REELS",
        "async_upload": "true",
        "request_id": rid,
    }
    with open(job["video_path"], "rb") as f:
        r = httpx.post(f"{BASE}/upload", headers=headers, data=data,
                       files={"video": (f"{job['id']}.mp4", f, "video/mp4")},
                       timeout=httpx.Timeout(300, connect=30))
    try:
        js = r.json()
    except Exception:
        js = {}
    if r.status_code >= 400:
        raise UploadError(js.get("message") or js.get("error") or r.text[:300])
    return js


def _poll(rid):
    headers = {"Authorization": f"Apikey {UPLOADPOST_API_KEY}"}
    time.sleep(5)
    js = {}
    for _ in range(90):  # ~15 min
        r = httpx.get(f"{BASE}/uploadposts/status", params={"request_id": rid},
                      headers=headers, timeout=30)
        js = r.json() if r.status_code == 200 else {}
        total, done = js.get("total"), js.get("completed")
        if js.get("status") in ("completed", "failed") or (total and done and done >= total):
            return js, True
        time.sleep(10)
    return js, False


def run_job(job_id, notify):
    """notify(text, retry=False). Runs in a worker thread after Telegram approval."""
    job = db.get(job_id)
    attempts = (job.get("attempts") or 0) + 1
    db.update(job_id, attempts=attempts)
    rid = f"{job_id}-{attempts}"
    try:
        js = _send(job, rid)
        finished = True
        if "results" not in js:
            js, finished = _poll(rid)
        items = _norm(js.get("results"))
        ig = [r for p, r in items if p == "instagram"] or [r for _, r in items]
        if not finished and not ig:
            db.update(job_id, status="uploading", detail=f"request_id={rid}")
            notify(f"⏳ ریل #{job_id} هنوز در حال پردازش است (request_id: {rid}). داخل upload-post چک کن.")
            return
        ok = any(r.get("success") for r in ig)
        url = next((r.get("url") for r in ig if r.get("url")), "") or ""
        if ok:
            db.update(job_id, status="published", url=url, detail="")
            notify(f"✅ ریل #{job_id} منتشر شد.\n{url}".strip())
            db.remove_video(job_id)
        else:
            msg = next((r.get("error") or r.get("message") for r in ig
                        if r.get("error") or r.get("message")), "نامشخص")
            raise UploadError(str(msg))
    except Exception as e:
        log.exception("upload failed")
        db.update(job_id, status="failed", detail=str(e)[:500])
        notify(f"❌ آپلود ریل #{job_id} ناموفق بود:\n{str(e)[:500]}", retry=True)
