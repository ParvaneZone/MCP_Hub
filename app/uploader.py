import logging
import time

import httpx

from . import db, zernio
from .config import UPLOADPOST_API_KEYS, UPLOADPOST_USER

log = logging.getLogger("uploader")
BASE = "https://api.upload-post.com/api"


class UploadError(Exception):
    pass


def _label(key):
    """شماره و چهار کاراکتر آخر کلید؛ برای مشخص شدن اکانت مشکل‌دار."""
    return f"key #{UPLOADPOST_API_KEYS.index(key) + 1} (...{key[-4:]})"


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


class _KeyFailed(UploadError):
    """این کلید جواب نداد (لیمیت/نامعتبر/خطای سرور)؛ برو سراغ بعدی."""


def _send(job, rid, key):
    headers = {"Authorization": f"Apikey {key}", "Idempotency-Key": rid}
    data = {
        "user": UPLOADPOST_USER,
        "platform[]": "instagram",
        "title": job["caption"],
        "media_type": "REELS",
        "async_upload": "true",
        "request_id": rid,
    }
    try:
        with open(job["video_path"], "rb") as f:
            r = httpx.post(f"{BASE}/upload", headers=headers, data=data,
                           files={"video": (f"{job['id']}.mp4", f, "video/mp4")},
                           timeout=httpx.Timeout(300, connect=30))
    except httpx.HTTPError as e:
        raise _KeyFailed(f"network: {e}")
    try:
        js = r.json()
    except Exception:
        js = {}
    if r.status_code >= 400:
        msg = js.get("message") or js.get("error") or r.text[:300]
        if r.status_code in (401, 402, 403, 429) or r.status_code >= 500:
            raise _KeyFailed(f"HTTP {r.status_code}: {msg}")
        raise UploadError(msg)
    return js


def _send_any(job, rid):
    """کلیدها را به ترتیب امتحان می‌کند؛ (پاسخ، کلید موفق) را برمی‌گرداند."""
    errors = []
    for key in UPLOADPOST_API_KEYS:
        try:
            return _send(job, rid, key), key
        except _KeyFailed as e:
            log.warning("upload-post %s failed: %s", _label(key), e)
            errors.append(f"{_label(key)}: {e}")
        except UploadError as e:
            raise UploadError(f"{_label(key)}: {e}")
    raise UploadError("همه‌ی API keyها ناموفق بودند:\n" + "\n".join(errors))


def _poll(rid, key):
    headers = {"Authorization": f"Apikey {key}"}
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


def _try_zernio(job_id, job, notify):
    """آپلودر اصلی. True یعنی کار تمام شد (منتشر یا در حال پردازش)؛
    False یعنی خطا تلگرام شد و باید به upload-post رفت."""
    try:
        res = zernio.publish(job)
    except Exception as e:
        log.warning("zernio failed: %s", e)
        notify(f"⚠️ ارسال ریل #{job_id} با Zernio ناموفق بود:\n{str(e)[:500]}\n\n↪️ دارم با upload-post امتحان می‌کنم…")
        return False
    if res["status"] == "published":
        db.update(job_id, status="published", url=res["url"], detail="")
        notify(f"✅ ریل #{job_id} از طریق Zernio منتشر شد.\n{res['url']}".strip())
        db.remove_video(job_id)
    else:
        db.update(job_id, status="uploading", detail=f"zernio post_id={res['post_id']}")
        notify(f"⏳ ریل #{job_id} در Zernio هنوز در حال پردازش است (post_id: {res['post_id']}). برای جلوگیری از پست تکراری از upload-post استفاده نشد.")
    return True


def run_job(job_id, notify):
    """notify(text, retry=False). Runs in a worker thread after Telegram approval."""
    job = db.get(job_id)
    attempts = (job.get("attempts") or 0) + 1
    db.update(job_id, attempts=attempts)
    rid = f"{job_id}-{attempts}"
    try:
        if zernio.enabled() and _try_zernio(job_id, job, notify):
            return
        js, key = _send_any(job, rid)
        finished = True
        if "results" not in js:
            js, finished = _poll(rid, key)
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
            raise UploadError(f"{_label(key)}: {msg}")
    except Exception as e:
        log.exception("upload failed")
        db.update(job_id, status="failed", detail=str(e)[:500])
        notify(f"❌ آپلود ریل #{job_id} ناموفق بود:\n{str(e)[:500]}", retry=True)
