import os
import sqlite3
import time
from contextlib import closing

from .config import DATA_DIR


def _c():
    c = sqlite3.connect(str(DATA_DIR / "reels.db"), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _run(sql, args=(), one=False, many=False, rowcount=False):
    with closing(_c()) as c:
        cur = c.execute(sql, args)
        c.commit()
        if rowcount:
            return cur.rowcount
        if one:
            r = cur.fetchone()
            return dict(r) if r else None
        if many:
            return [dict(r) for r in cur.fetchall()]


def init():
    _run("""CREATE TABLE IF NOT EXISTS jobs(
        id TEXT PRIMARY KEY, status TEXT, caption TEXT, video_path TEXT,
        theme TEXT, detail TEXT DEFAULT '', url TEXT DEFAULT '',
        attempts INTEGER DEFAULT 0, tg_message_id INTEGER,
        created REAL, updated REAL)""")


def create(job_id, caption, video_path, theme):
    now = time.time()
    _run("INSERT INTO jobs(id,status,caption,video_path,theme,created,updated) VALUES(?,?,?,?,?,?,?)",
         (job_id, "pending", caption, video_path, theme, now, now))


def get(job_id):
    return _run("SELECT * FROM jobs WHERE id=?", (job_id,), one=True)


def update(job_id, **fields):
    fields["updated"] = time.time()
    keys = ",".join(f"{k}=?" for k in fields)
    _run(f"UPDATE jobs SET {keys} WHERE id=?", (*fields.values(), job_id))


def claim(job_id, from_status, to_status):
    """Atomic state change; True only for the single caller that wins."""
    n = _run("UPDATE jobs SET status=?, updated=? WHERE id=? AND status=?",
             (to_status, time.time(), job_id, from_status), rowcount=True)
    return n == 1


def recent(n=10):
    return _run("SELECT id,status,caption,url,detail,created FROM jobs ORDER BY created DESC LIMIT ?",
                (n,), many=True)


def remove_video(job_id):
    j = get(job_id)
    if j and j["video_path"] and os.path.exists(j["video_path"]):
        try:
            os.remove(j["video_path"])
        except OSError:
            pass


def expire_pending(ttl_seconds):
    old = _run("SELECT id FROM jobs WHERE status='pending' AND created<?",
               (time.time() - ttl_seconds,), many=True)
    done = []
    for r in old:
        if claim(r["id"], "pending", "expired"):
            remove_video(r["id"])
            done.append(r["id"])
    return done


def purge_old(days=7):
    old = _run("SELECT id FROM jobs WHERE status NOT IN ('pending','uploading') AND updated<?",
               (time.time() - days * 86400,), many=True)
    for r in old:
        remove_video(r["id"])
