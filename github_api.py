import base64
import httpx


class GitHubError(ValueError):
    pass


class GitHub:
    def __init__(self, token: str):
        self.c = httpx.AsyncClient(base_url="https://api.github.com", timeout=30, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "claude-github-mcp"})

    async def req(self, method: str, url: str, **kw):
        try: r = await self.c.request(method, url, **kw)
        except httpx.HTTPError as e: raise GitHubError(f"اتصال به GitHub ناموفق: {type(e).__name__}") from None
        if r.status_code >= 400:
            try: msg = r.json().get("message", "")
            except Exception: msg = ""
            raise GitHubError(f"GitHub {r.status_code}: {msg[:200]}")
        return r.json() if r.content else {}

    async def default_branch(self, repo: str) -> str:
        return (await self.req("GET", f"/repos/{repo}"))["default_branch"]

    async def branch_sha(self, repo: str, branch: str) -> str:
        return (await self.req("GET", f"/repos/{repo}/git/ref/heads/{branch}"))["object"]["sha"]

    async def list_files(self, repo: str, ref: str, prefix: str, limit: int = 500):
        t = await self.req("GET", f"/repos/{repo}/git/trees/{ref}", params={"recursive": "1"})
        items = [{"path": e["path"], "size": e.get("size", 0)} for e in t.get("tree", []) if e["type"] == "blob" and e["path"].startswith(prefix)]
        return {"files": items[:limit], "total": len(items), "truncated": len(items) > limit or bool(t.get("truncated"))}

    async def read_file(self, repo: str, path: str, ref: str, max_bytes: int = 200_000) -> str:
        d = await self.req("GET", f"/repos/{repo}/contents/{path}", params={"ref": ref})
        if isinstance(d, list): raise GitHubError("این مسیر پوشه است؛ از list_files استفاده کن")
        if d.get("encoding") != "base64": raise GitHubError("فایل بزرگ‌تر از ۱MB است و قابل خواندن نیست")
        raw = base64.b64decode(d["content"])
        if len(raw) > max_bytes: raise GitHubError(f"فایل {len(raw)} بایت است (سقف {max_bytes})")
        try: return raw.decode("utf-8")
        except UnicodeDecodeError: raise GitHubError("فایل باینری است") from None

    async def create_branch(self, repo: str, branch: str, from_branch: str) -> str:
        sha = await self.branch_sha(repo, from_branch)
        await self.req("POST", f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})
        return sha

    async def commit(self, repo: str, branch: str, message: str, files: dict[str, str], deletes: list[str]) -> str:
        head = await self.branch_sha(repo, branch)
        base_tree = (await self.req("GET", f"/repos/{repo}/git/commits/{head}"))["tree"]["sha"]
        tree = [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in files.items()]
        tree += [{"path": p, "mode": "100644", "type": "blob", "sha": None} for p in deletes]
        nt = await self.req("POST", f"/repos/{repo}/git/trees", json={"base_tree": base_tree, "tree": tree})
        nc = await self.req("POST", f"/repos/{repo}/git/commits", json={"message": message, "tree": nt["sha"], "parents": [head]})
        await self.req("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", json={"sha": nc["sha"], "force": False})
        return nc["sha"]

    async def pull_request(self, repo: str, head: str, base: str, title: str, body: str) -> dict:
        d = await self.req("POST", f"/repos/{repo}/pulls", json={"title": title, "head": head, "base": base, "body": body})
        return {"number": d["number"], "url": d["html_url"]}
