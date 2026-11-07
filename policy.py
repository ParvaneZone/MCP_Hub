"""قوانین: متن آزاد برای Claude (RULES.md) + سیاست اجباری سرور (policy.json). هر دو در هر درخواست دوباره خوانده می‌شوند،
پس تغییرشان نیاز به ری‌استارت ندارد. هرچه در policy.json باشد سرور خودش اجرا می‌کند؛ حتی اگر Claude اشتباه کند."""
import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULTS = {
    "allowed_repos": [],                 # خالی = از ALLOWED_REPOS در .env
    "branch_prefix": "claude/",          # Claude فقط روی شاخه‌هایی که با این شروع شوند می‌نویسد
    "protected_branches": ["main", "master"],
    "protected_paths": [".github/workflows/*", ".env", "*.pem", "*.key"],   # نوشتن/حذف ممنوع
    "blocked_read_paths": [".env", "*.pem", "*.key"],                       # خواندن ممنوع
    "max_files_per_commit": 40,
    "max_file_bytes": 300_000,
    "max_total_bytes": 1_000_000,
    "block_secrets": True,
    "allow_delete": True,
    "commit_message_regex": "^.{5,200}$",
}

SECRET_PATTERNS = {
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "GitHub fine-grained token": r"github_pat_[A-Za-z0-9_]{40,}",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "AWS key id": r"AKIA[0-9A-Z]{16}",
    "Private key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "Telegram bot token": r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b",
}


class PolicyError(ValueError):
    pass


def _match(path: str, pats: list[str]) -> bool:
    base = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, p) or ("/" not in p and fnmatch.fnmatch(base, p)) for p in pats)


@dataclass
class Snapshot:
    rules: str
    cfg: dict
    version: str

    def public(self) -> dict:
        keys = ("allowed_repos", "branch_prefix", "protected_branches", "protected_paths", "blocked_read_paths",
                "max_files_per_commit", "max_file_bytes", "max_total_bytes", "block_secrets", "allow_delete", "commit_message_regex")
        return {k: self.cfg[k] for k in keys}

    def check_repo(self, repo: str) -> str:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo or ""):
            raise PolicyError("نام ریپو باید به شکل owner/name باشد")
        if repo.lower() not in [r.lower() for r in self.cfg["allowed_repos"]]:
            raise PolicyError(f"ریپوی «{repo}» در لیست مجاز نیست")
        return repo

    def check_branch_name(self, branch: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", branch or "") or ".." in branch or branch.endswith(("/", ".lock")) or branch.startswith(("/", "-")):
            raise PolicyError("نام شاخه نامعتبر است")
        return branch

    def check_write_branch(self, branch: str) -> str:
        self.check_branch_name(branch)
        if branch in self.cfg["protected_branches"]:
            raise PolicyError(f"نوشتن مستقیم روی «{branch}» ممنوع است؛ روی یک شاخه‌ی جدید بنویس و Pull Request باز کن")
        pre = self.cfg["branch_prefix"]
        if pre and not branch.startswith(pre):
            raise PolicyError(f"نام شاخه باید با «{pre}» شروع شود")
        return branch

    def check_path(self, path: str, write: bool) -> str:
        if (not isinstance(path, str) or not path or len(path) > 200 or path.startswith("/") or "\\" in path
                or any(ord(c) < 32 for c in path) or any(p in ("", ".", "..", ".git") for p in path.split("/"))):
            raise PolicyError(f"مسیر نامعتبر: {path!r}")
        if write and _match(path, self.cfg["protected_paths"]):
            raise PolicyError(f"مسیر «{path}» محافظت‌شده است و Claude اجازه‌ی تغییرش را ندارد")
        if not write and _match(path, self.cfg["blocked_read_paths"]):
            raise PolicyError(f"خواندن «{path}» ممنوع است")
        return path

    def check_commit(self, files: dict[str, str], deletes: list[str], message: str) -> None:
        c = self.cfg
        if not files and not deletes: raise PolicyError("هیچ فایلی برای کامیت داده نشده")
        if len(files) + len(deletes) > c["max_files_per_commit"]:
            raise PolicyError(f"حداکثر {c['max_files_per_commit']} فایل در هر کامیت؛ کار را به چند کامیت تقسیم کن")
        if deletes and not c["allow_delete"]: raise PolicyError("حذف فایل مجاز نیست")
        if set(files) & set(deletes): raise PolicyError("یک مسیر هم در نوشتن و هم در حذف آمده")
        if c["commit_message_regex"] and not re.fullmatch(c["commit_message_regex"], message or "", re.S):
            raise PolicyError(f"پیام کامیت با الگوی مجاز نمی‌خواند: {c['commit_message_regex']}")
        total = 0
        for p in [*files, *deletes]: self.check_path(p, write=True)
        for p, text in files.items():
            n = len(text.encode("utf-8")); total += n
            if n > c["max_file_bytes"]: raise PolicyError(f"«{p}» بزرگ‌تر از {c['max_file_bytes']} بایت است")
            if c["block_secrets"]:
                for name, pat in SECRET_PATTERNS.items():
                    if re.search(pat, text): raise PolicyError(f"در «{p}» چیزی شبیه {name} پیدا شد؛ راز را داخل کد نگذار")
        if total > c["max_total_bytes"]: raise PolicyError(f"مجموع حجم از {c['max_total_bytes']} بایت بیشتر است")


def load(rules_file: str | Path, policy_file: str | Path, env_repos: str = "") -> Snapshot:
    rules = Path(rules_file).read_text(encoding="utf-8") if Path(rules_file).exists() else ""
    user = json.loads(Path(policy_file).read_text(encoding="utf-8")) if Path(policy_file).exists() else {}
    cfg = {**DEFAULTS, **{k: v for k, v in user.items() if k in DEFAULTS}}
    if not cfg["allowed_repos"]:
        cfg["allowed_repos"] = [r.strip() for r in env_repos.split(",") if r.strip()]
    blob = rules + "\n" + json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    return Snapshot(rules, cfg, hashlib.sha256(blob.encode()).hexdigest()[:12])
