"""هر اکانت Claude یک «کلاینت» با راز مخصوص خودش است. فقط هش راز ذخیره می‌شود (خودِ راز فقط هنگام ساخت یک‌بار نشان داده می‌شود)."""
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _h(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass
class Client:
    name: str
    hash: str
    prefix: str = ""                      # پیشوند شاخه‌های این اکانت، مثل claude/acc1/
    repos: list[str] = field(default_factory=list)   # خالی = همه‌ی ریپوهای مجاز policy
    read_only: bool = False
    disabled: bool = False
    max_writes_per_hour: int = 30


class Clients:
    def __init__(self, path: Path, legacy_secret: str = "", base_prefix: str = "claude/"):
        self.path, self.legacy, self.base = Path(path), legacy_secret, base_prefix

    def _raw(self) -> list[dict]:
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError: return []

    def all(self) -> list[Client]:
        out = []
        for d in self._raw():
            c = Client(**{k: v for k, v in d.items() if k in Client.__dataclass_fields__})
            if not c.prefix.startswith(self.base): c.prefix = f"{self.base}{c.name}/"
            out.append(c)
        if self.legacy: out.append(Client("default", _h(self.legacy), prefix=self.base))
        return out

    def find(self, secret: str) -> Client | None:
        """مقایسه‌ی ثابت‌زمان با همه‌ی کلاینت‌ها (بدون خروج زودهنگام)."""
        hit, h = None, _h(secret)
        for c in self.all():
            if hmac.compare_digest(h, c.hash) and not c.disabled: hit = c
        return hit

    def _save(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.chmod(0o600); tmp.replace(self.path)

    def add(self, name: str, repos: list[str] | None = None, read_only: bool = False, max_writes: int = 30) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", name): raise ValueError("نام فقط حروف کوچک انگلیسی، عدد و - (حداکثر ۳۱)")
        rows = self._raw()
        if any(r["name"] == name for r in rows) or (name == "default" and self.legacy): raise ValueError("این نام قبلاً هست")
        secret = secrets.token_hex(24)
        rows.append({"name": name, "hash": _h(secret), "prefix": f"{self.base}{name}/", "repos": repos or [],
                     "read_only": read_only, "disabled": False, "max_writes_per_hour": max_writes})
        self._save(rows); return secret

    def rotate(self, name: str) -> str:
        rows = self._raw(); r = next((r for r in rows if r["name"] == name), None)
        if not r: raise ValueError("چنین اکانتی نیست")
        secret = secrets.token_hex(24); r["hash"] = _h(secret); self._save(rows); return secret

    def set_flag(self, name: str, **kw) -> None:
        rows = self._raw(); r = next((r for r in rows if r["name"] == name), None)
        if not r: raise ValueError("چنین اکانتی نیست")
        r.update(kw); self._save(rows)

    def remove(self, name: str) -> None:
        rows = self._raw(); new = [r for r in rows if r["name"] != name]
        if len(new) == len(rows): raise ValueError("چنین اکانتی نیست")
        self._save(new)
