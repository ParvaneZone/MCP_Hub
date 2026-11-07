"""MCP server: Claude کد را می‌نویسد، این سرور با توکن شما روی GitHub کامیت می‌کند، آن هم طبق قوانین."""
import contextvars
import json
import os
import time
from pathlib import Path
from pydantic import BaseModel
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
import policy
from clients import Client, Clients
from github_api import GitHub, GitHubError

TOKEN = os.environ["GITHUB_TOKEN"]
SECRET = os.environ.get("MCP_SECRET", "")      # اختیاری: اکانت «default»؛ اکانت‌های دیگر با manage.py ساخته می‌شوند
HOST = os.environ.get("PUBLIC_HOST", "")
CONFIG = Path(os.environ.get("CONFIG_DIR", "./config"))
DATA = Path(os.environ.get("DATA_DIR", "./data")); DATA.mkdir(parents=True, exist_ok=True)
if SECRET and len(SECRET) < 24: raise SystemExit("MCP_SECRET باید حداقل ۲۴ کاراکتر باشد")
BASE_PREFIX = policy.load(CONFIG / "RULES.md", CONFIG / "policy.json").cfg["branch_prefix"]
CLIENTS = Clients(DATA / "clients.json", SECRET, BASE_PREFIX)
CURRENT: contextvars.ContextVar[Client | None] = contextvars.ContextVar("client", default=None)
_writes: dict[str, list[float]] = {}

gh = GitHub(TOKEN)
INSTRUCTIONS = ("قبل از هر کاری get_rules را صدا بزن و دقیقاً طبق قوانین برگشتی عمل کن. "
                "هر نوشتن (write_files) به rules_version همان پاسخ نیاز دارد؛ اگر قوانین عوض شده باشند رد می‌شود. "
                "روی شاخه‌ی اصلی نمی‌نویسی؛ شاخه‌ی جدید بساز، کامیت کن و Pull Request باز کن.")
mcp = FastMCP("github-pusher", instructions=INSTRUCTIONS, stateless_http=True,
              transport_security=TransportSecuritySettings(
                  enable_dns_rebinding_protection=bool(HOST), allowed_hosts=[HOST, f"{HOST}:*"] if HOST else [],
                  allowed_origins=["https://claude.ai", f"https://{HOST}"] if HOST else []))


def snap() -> policy.Snapshot:
    return policy.load(CONFIG / "RULES.md", CONFIG / "policy.json", os.environ.get("ALLOWED_REPOS", ""))


def who() -> Client:
    c = CURRENT.get()
    if c is None: raise policy.PolicyError("اکانت شناسایی نشد")
    return c


def audit(action: str, **kw) -> None:
    with (DATA / "audit.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "client": who().name, "action": action, **kw}, ensure_ascii=False) + "\n")


def repo_ok(s: policy.Snapshot, repo: str) -> str:
    c = who(); s.check_repo(repo)
    if c.repos and repo.lower() not in [r.lower() for r in c.repos]: raise policy.PolicyError(f"اکانت «{c.name}» به ریپوی «{repo}» دسترسی ندارد")
    return repo


def write_ok(s: policy.Snapshot, repo: str, branch: str) -> None:
    """مجوز نوشتن: ریپو، شاخه‌ی مخصوص همین اکانت، فقط‌خواندنی نبودن و سقف نوشتن در ساعت."""
    c = who(); repo_ok(s, repo); s.check_write_branch(branch)
    if c.read_only: raise policy.PolicyError(f"اکانت «{c.name}» فقط‌خواندنی است")
    if not branch.startswith(c.prefix): raise policy.PolicyError(f"شاخه‌ی این اکانت باید با «{c.prefix}» شروع شود")
    now = time.time(); w = [t for t in _writes.get(c.name, []) if now - t < 3600]
    if len(w) >= c.max_writes_per_hour: raise policy.PolicyError("سقف نوشتن در ساعت پر شده؛ کمی بعد دوباره تلاش کن")
    w.append(now); _writes[c.name] = w


class FileItem(BaseModel):
    path: str
    content: str


@mcp.tool()
def get_rules() -> dict:
    """قوانین فعلی را برمی‌گرداند. همیشه اول این را صدا بزن و طبق rules_markdown عمل کن؛ rules_version را برای write_files نگه دار."""
    s = snap(); c = who()
    return {"rules_version": s.version, "rules_markdown": s.rules, "enforced_policy": s.public(),
            "you_are": {"account": c.name, "branch_prefix": c.prefix, "read_only": c.read_only, "repos": c.repos or "all allowed"}}


@mcp.tool()
def list_repos() -> list[str]:
    """ریپوهای مجاز برای همین اکانت."""
    c = who(); allowed = snap().cfg["allowed_repos"]
    return [r for r in allowed if not c.repos or r.lower() in [x.lower() for x in c.repos]]


@mcp.tool()
async def list_files(repo: str, path_prefix: str = "", ref: str = "") -> dict:
    """فهرست فایل‌های ریپو (حداکثر ۵۰۰ مورد). ref = شاخه؛ خالی یعنی شاخه‌ی پیش‌فرض."""
    s = snap(); repo_ok(s, repo)
    ref = ref or await gh.default_branch(repo)
    return {"ref": ref, **await gh.list_files(repo, s.check_branch_name(ref), path_prefix)}


@mcp.tool()
async def read_file(repo: str, path: str, ref: str = "") -> str:
    """محتوای یک فایل متنی. ref = شاخه؛ خالی یعنی شاخه‌ی پیش‌فرض."""
    s = snap(); repo_ok(s, repo); s.check_path(path, write=False)
    ref = ref or await gh.default_branch(repo)
    return await gh.read_file(repo, path, s.check_branch_name(ref))


@mcp.tool()
async def create_branch(repo: str, branch: str, from_branch: str = "") -> dict:
    """شاخه‌ی جدید برای کار (نام باید با پیشوند مجاز شروع شود، مثل claude/telegram-fix)."""
    s = snap(); write_ok(s, repo, branch)
    base = from_branch or await gh.default_branch(repo)
    sha = await gh.create_branch(repo, branch, s.check_branch_name(base))
    audit("create_branch", repo=repo, branch=branch, base=base)
    return {"branch": branch, "from": base, "sha": sha}


@mcp.tool()
async def write_files(repo: str, branch: str, message: str, files: list[FileItem], rules_version: str, delete_paths: list[str] = []) -> dict:
    """همه‌ی فایل‌ها را در «یک» کامیت روی شاخه می‌نویسد. content باید متن کامل فایل باشد. rules_version را از get_rules بگیر."""
    s = snap()
    if rules_version != s.version: raise policy.PolicyError("قوانین عوض شده یا get_rules صدا زده نشده؛ دوباره get_rules را صدا بزن و طبق آن عمل کن")
    write_ok(s, repo, branch)
    fm = {f.path: f.content for f in files}
    if len(fm) != len(files): raise policy.PolicyError("مسیر تکراری در files")
    s.check_commit(fm, delete_paths, message)
    sha = await gh.commit(repo, branch, message, fm, delete_paths)
    audit("commit", repo=repo, branch=branch, sha=sha, files=list(fm), deleted=delete_paths, message=message[:200])
    return {"commit": sha, "url": f"https://github.com/{repo}/commit/{sha}", "files": len(fm), "deleted": len(delete_paths)}


@mcp.tool()
async def open_pull_request(repo: str, branch: str, title: str, body: str = "", base: str = "") -> dict:
    """Pull Request از شاخه‌ی کار به شاخه‌ی اصلی. مرج را خود مالک انجام می‌دهد."""
    s = snap(); write_ok(s, repo, branch)
    base = base or await gh.default_branch(repo)
    pr = await gh.pull_request(repo, branch, s.check_branch_name(base), title[:200], body[:5000])
    audit("pull_request", repo=repo, branch=branch, **pr)
    return pr


class SecretPath:
    """ASGI: /<راز-اکانت>/... → اکانت شناسایی می‌شود؛ هر مسیر دیگر 404 (تا وجود سرویس لو نرود)."""
    def __init__(self, app, clients: Clients): self.app, self.clients = app, clients

    async def _reply(self, send, status: int, body: bytes = b""):
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan": return await self.app(scope, receive, send)
        if scope["type"] != "http": return
        path = scope["path"]
        if path == "/health": return await self._reply(send, 200, b"ok")
        seg = path.split("/")[1] if path.startswith("/") else ""
        client = self.clients.find(seg) if len(seg) >= 24 else None
        if client is None: return await self._reply(send, 404)
        new = path[len(seg) + 1:] or "/"
        tok = CURRENT.set(client)
        try: await self.app({**scope, "path": new, "raw_path": new.encode()}, receive, send)
        finally: CURRENT.reset(tok)


app = SecretPath(mcp.streamable_http_app(), CLIENTS)
