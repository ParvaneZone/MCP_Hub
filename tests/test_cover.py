"""Tests for the custom reel cover. Run from the repo root: python -m unittest discover -s tests"""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from app import cover, db, telegram_bot, zernio  # noqa: E402


def _png(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _touch(name, data=b"x"):
    p = os.path.join(_TMP, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


class CoverImageTest(unittest.TestCase):
    def test_square_becomes_9x16_jpeg(self):
        out = os.path.join(_TMP, "c1.jpg")
        cover.normalize(_png(600, 600), out)
        img = Image.open(out)
        self.assertEqual(img.size, (1080, 1920))
        self.assertEqual(img.format, "JPEG")

    def test_non_image_raises(self):
        with self.assertRaises(Exception):
            cover.normalize(b"not an image", os.path.join(_TMP, "bad.jpg"))


class DbTest(unittest.TestCase):
    def setUp(self):
        db._run("DROP TABLE IF EXISTS jobs")
        db.init()

    def test_migration_adds_cover_column_to_old_table(self):
        db._run("DROP TABLE jobs")
        db._run("""CREATE TABLE jobs(
            id TEXT PRIMARY KEY, status TEXT, caption TEXT, video_path TEXT,
            theme TEXT, detail TEXT DEFAULT '', url TEXT DEFAULT '',
            attempts INTEGER DEFAULT 0, tg_message_id INTEGER,
            created REAL, updated REAL)""")
        db.init()
        db.create("old00001", "c", "/x.mp4", "navy")
        db.set_cover("old00001", "/y.jpg")
        self.assertEqual(db.get("old00001")["cover_path"], "/y.jpg")

    def test_remove_video_also_deletes_cover(self):
        video, img = _touch("v.mp4"), _touch("v.jpg")
        db.create("del00001", "c", video, "navy")
        db.set_cover("del00001", img)
        db.remove_video("del00001")
        self.assertFalse(os.path.exists(video))
        self.assertFalse(os.path.exists(img))


class PickJobTest(unittest.TestCase):
    def setUp(self):
        db._run("DROP TABLE IF EXISTS jobs")
        db.init()
        db.create("aaaa1111", "c", "/a.mp4", "navy")
        db.update("aaaa1111", tg_message_id=500)

    def test_reply_to_preview_video(self):
        job = telegram_bot._pick_job({"reply_to_message": {"message_id": 500}})
        self.assertEqual(job["id"], "aaaa1111")

    def test_reply_to_caption_message(self):
        msg = {"reply_to_message": {"message_id": 501, "reply_to_message": {"message_id": 500}}}
        self.assertEqual(telegram_bot._pick_job(msg)["id"], "aaaa1111")

    def test_reel_id_in_caption(self):
        db.create("bbbb2222", "c", "/b.mp4", "navy")
        job = telegram_bot._pick_job({"caption": "cover for #bbbb2222"})
        self.assertEqual(job["id"], "bbbb2222")

    def test_single_pending_reel_is_default(self):
        self.assertEqual(telegram_bot._pick_job({})["id"], "aaaa1111")

    def test_ambiguous_returns_none(self):
        db.create("bbbb2222", "c", "/b.mp4", "navy")
        self.assertIsNone(telegram_bot._pick_job({}))


class _Resp:
    def __init__(self, status=200, js=None):
        self.status_code, self._js, self.text = status, js or {}, ""

    def json(self):
        return self._js


class ZernioCoverTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.fail_cover = False
        self._orig = zernio._request
        zernio._request = self._fake
        self.job = {"id": "J1", "caption": "hi", "video_path": _touch("j1.mp4"),
                    "cover_path": _touch("j1.jpg")}

    def tearDown(self):
        zernio._request = self._orig

    def _fake(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if url.endswith("/media/presign"):
            name = kw["json"]["filename"]
            if self.fail_cover and name.endswith("-cover.jpg"):
                return _Resp(500, {"error": "boom"})
            return _Resp(200, {"uploadUrl": f"https://up/{name}", "publicUrl": f"https://pub/{name}"})
        if method == "PUT":
            return _Resp(200)
        return _Resp(200, {"post": {"_id": "p1", "platforms": [
            {"platform": "instagram", "status": "published", "platformPostUrl": "https://ig/x"}]}})

    def _post_body(self):
        return next(kw["json"] for m, u, kw in self.calls if m == "POST" and u.endswith("/posts"))

    def test_cover_is_sent_as_instagram_thumbnail(self):
        res = zernio.publish(self.job)
        item = self._post_body()["mediaItems"][0]
        self.assertEqual(item["url"], "https://pub/J1.mp4")
        self.assertEqual(item["instagramThumbnail"], "https://pub/J1-cover.jpg")
        self.assertFalse(res["cover_failed"])

    def test_no_cover_means_no_thumbnail_field(self):
        self.job["cover_path"] = ""
        zernio.publish(self.job)
        self.assertNotIn("instagramThumbnail", self._post_body()["mediaItems"][0])

    def test_cover_upload_failure_still_publishes(self):
        self.fail_cover = True
        res = zernio.publish(self.job)
        self.assertEqual(res["status"], "published")
        self.assertTrue(res["cover_failed"])
        self.assertNotIn("instagramThumbnail", self._post_body()["mediaItems"][0])


if __name__ == "__main__":
    unittest.main()
