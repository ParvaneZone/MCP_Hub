"""Zernio client: publish a Reel to Instagram (primary uploader).

Flow (docs.zernio.com):
  1. POST /v1/media/presign  -> uploadUrl + publicUrl
  2. PUT file to uploadUrl   (no Authorization header)
  3. POST /v1/posts          with publicUrl in mediaItems, publishNow=true
"""
import logging
import time

import httpx

from .config import ZERNIO_ACCOUNT_ID, ZERNIO_API_KEY, ZERNIO_BASE

log = logging.getLogger("zernio")


class ZernioError(Exception):
    pass


def enabled():
    return bool(ZERNIO_API_KEY and ZERNIO_ACCOUNT_ID)


def _headers():
    return {"Authorization": f"Bearer {ZERNIO_API_KEY}"}


def _err(r):
    try:
        js = r.json()
    except Exception:
        js = {}
    msg = js.get("error") or js.get("message") or r.text[:300]
    param = js.get("param")
    return f"HTTP {r.status_code}: {msg}" + (f" (param: {param})" if param else "")


def _request(method, url, **kw):
    try:
        return httpx.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise ZernioError(f"network: {e}")


def _upload_video(job):
    r = _request("POST", f"{ZERNIO_BASE}/media/presign", headers=_headers(),
                 json={"filename": f"{job['id']}.mp4", "contentType": "video/mp4"}, timeout=30)
    if r.status_code >= 400:
        raise ZernioError(f"presign failed - {_err(r)}")
    js = r.json()
    upload_url, public_url = js.get("uploadUrl"), js.get("publicUrl")
    if not upload_url or not public_url:
        raise ZernioError(f"presign response incomplete: {str(js)[:200]}")
    with open(job["video_path"], "rb") as f:
        data = f.read()
    r = _request("PUT", upload_url, content=data, headers={"Content-Type": "video/mp4"},
                 timeout=httpx.Timeout(300, connect=30))
    if r.status_code >= 400:
        raise ZernioError(f"file upload failed - HTTP {r.status_code}: {r.text[:200]}")
    return public_url


def _platform_result(post):
    """(status, url, error) of the instagram entry of a post object."""
    plats = post.get("platforms") or []
    p = next((x for x in plats if x.get("platform") == "instagram"), plats[0] if plats else {})
    err = p.get("error") or p.get("errorMessage") or p.get("message") or ""
    return (p.get("status") or ""), (p.get("platformPostUrl") or ""), str(err)


def publish(job):
    """Publish the job's video as an Instagram Reel.

    Returns {"status": "published"|"pending", "url": str, "post_id": str}.
    Raises ZernioError on any failure (caller falls back to upload-post).
    """
    public_url = _upload_video(job)
    body = {
        "content": (job["caption"] or "")[:2200],
        "mediaItems": [{"url": public_url, "type": "video"}],
        "platforms": [{"platform": "instagram", "accountId": ZERNIO_ACCOUNT_ID}],
        "publishNow": True,
    }
    r = _request("POST", f"{ZERNIO_BASE}/posts", headers=_headers(), json=body,
                 timeout=httpx.Timeout(120, connect=30))
    if r.status_code >= 400:
        raise ZernioError(f"create post failed - {_err(r)}")
    post = (r.json() or {}).get("post") or {}
    post_id = post.get("_id") or ""
    status, url, err = _platform_result(post)

    # Instagram may publish asynchronously: poll briefly.
    for _ in range(12):
        if status in ("published", "failed", "error") or not post_id:
            break
        time.sleep(10)
        g = _request("GET", f"{ZERNIO_BASE}/posts/{post_id}", headers=_headers(), timeout=30)
        if g.status_code != 200:
            continue
        post = (g.json() or {}).get("post") or {}
        status, url, err = _platform_result(post)

    if status == "published":
        return {"status": "published", "url": url, "post_id": post_id}
    if status in ("failed", "error"):
        raise ZernioError(err or "platform reported failure")
    # Still processing: do NOT fall back, or the reel could be posted twice.
    return {"status": "pending", "url": url, "post_id": post_id}
