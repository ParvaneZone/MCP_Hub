import json
import logging
import threading
import time

import httpx

from . import db, uploader
from .config import (APPROVAL_TTL_HOURS, TELEGRAM_API_BASE, TELEGRAM_BOT_TOKEN,
                     TELEGRAM_CHAT_ID)

log = logging.getLogger("telegram")
API = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}"


def call(method, data=None, files=None, timeout=60):
    r = httpx.post(f"{API}/{method}", data=data, files=files, timeout=timeout)
    j = r.json() if r.content else {}
    if not j.get("ok"):
        raise RuntimeError(f"telegram {method}: {j.get('description') or r.text[:200]}")
    return j["result"]


def send(text, markup=None):
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text[:4000]}
    if markup:
        data["reply_markup"] = json.dumps(markup)
    return call("sendMessage", data)


def send_preview(job_id, caption, video_path, secs):
    kb = {"inline_keyboard": [[
        {"text": "✅ تأیید و ارسال به اینستاگرام", "callback_data": f"ok:{job_id}"},
        {"text": "❌ رد", "callback_data": f"no:{job_id}"},
    ]]}
    with open(video_path, "rb") as f:
        res = call("sendVideo", {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": f"🎬 پیش‌نمایش ریل #{job_id}\n⏱ {secs:.0f} ثانیه\nتا تأیید نکنی چیزی ارسال نمی‌شود.",
            "reply_markup": json.dumps(kb),
            "supports_streaming": "true", "width": 1080, "height": 1920,
        }, {"video": (f"{job_id}.mp4", f, "video/mp4")}, timeout=300)
    call("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, "reply_to_message_id": res["message_id"],
                         "text": "📝 کپشن:\n\n" + caption[:3800]})
    return res["message_id"]


def _notifier(job_id):
    def notify(text, retry=False):
        markup = None
        if retry:
            markup = {"inline_keyboard": [[{"text": "🔁 تلاش دوباره", "callback_data": f"rt:{job_id}"}]]}
        try:
            send(text, markup)
        except Exception:
            log.exception("notify failed")
    return notify


def _strip_buttons(cb):
    try:
        call("editMessageReplyMarkup", {
            "chat_id": cb["message"]["chat"]["id"], "message_id": cb["message"]["message_id"],
            "reply_markup": json.dumps({"inline_keyboard": []})})
    except Exception:
        pass


def _answer(cb, text):
    try:
        call("answerCallbackQuery", {"callback_query_id": cb["id"], "text": text})
    except Exception:
        pass


def _start_upload(job_id):
    threading.Thread(target=uploader.run_job, args=(job_id, _notifier(job_id)), daemon=True).start()


def _on_callback(cb):
    if str(cb.get("message", {}).get("chat", {}).get("id")) != str(TELEGRAM_CHAT_ID):
        return
    action, _, job_id = (cb.get("data") or "").partition(":")
    if action == "ok" and db.claim(job_id, "pending", "uploading"):
        _answer(cb, "در حال ارسال…")
        _strip_buttons(cb)
        send(f"📤 ریل #{job_id} تأیید شد و دارد به upload-post ارسال می‌شود…")
        _start_upload(job_id)
    elif action == "no" and db.claim(job_id, "pending", "rejected"):
        _answer(cb, "رد شد")
        _strip_buttons(cb)
        db.remove_video(job_id)
        send(f"🚫 ریل #{job_id} رد شد و چیزی ارسال نشد.")
    elif action == "rt" and db.claim(job_id, "failed", "uploading"):
        _answer(cb, "تلاش دوباره…")
        _strip_buttons(cb)
        _start_upload(job_id)
    else:
        _answer(cb, "این ریل دیگر در انتظار تأیید نیست.")


def _on_message(msg):
    chat = str(msg["chat"]["id"])
    text = (msg.get("text") or "").strip()
    if text.startswith("/start"):
        call("sendMessage", {"chat_id": chat, "text": f"Chat ID شما: {chat}"})
        return
    if chat != str(TELEGRAM_CHAT_ID):
        return
    if text.startswith("/list"):
        rows = db.recent(8)
        lines = [f"#{r['id']} — {r['status']} — {(r['caption'] or '')[:30]}" for r in rows]
        send("\n".join(lines) or "هنوز ریلی ساخته نشده.")


def run():
    offset = 0
    last_clean = 0
    while True:
        try:
            if time.time() - last_clean > 300:
                last_clean = time.time()
                for jid in db.expire_pending(APPROVAL_TTL_HOURS * 3600):
                    send(f"⌛ ریل #{jid} تأیید نشد و منقضی شد.")
                db.purge_old()
            ups = call("getUpdates", {"offset": offset, "timeout": 30,
                                      "allowed_updates": json.dumps(["message", "callback_query"])},
                       timeout=45)
            for u in ups:
                offset = u["update_id"] + 1
                try:
                    if "callback_query" in u:
                        _on_callback(u["callback_query"])
                    elif "message" in u:
                        _on_message(u["message"])
                except Exception:
                    log.exception("update handling failed")
        except Exception:
            log.exception("polling error")
            time.sleep(5)
