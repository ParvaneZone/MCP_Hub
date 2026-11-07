"""مدیریت اکانت‌ها:  docker compose exec github-mcp python manage.py <دستور>
  add <نام> [--repos a/b,c/d] [--read-only] [--max-writes N]   ساخت اکانت و نشان دادن آدرس اتصال (فقط یک‌بار)
  list                      فهرست اکانت‌ها
  rotate <نام>              راز جدید (آدرس قبلی باطل می‌شود)
  disable <نام> / enable <نام>
  remove <نام>"""
import argparse
import os
import sys
from pathlib import Path
from clients import Clients

DATA = Path(os.environ.get("DATA_DIR", "./data"))
HOST = os.environ.get("PUBLIC_HOST", "دامنه‌ی-شما")
cl = Clients(DATA / "clients.json", os.environ.get("MCP_SECRET", ""))


def url(secret: str) -> str:
    return f"https://{HOST}/{secret}/mcp"


def main() -> int:
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("name"); a.add_argument("--repos", default=""); a.add_argument("--read-only", action="store_true"); a.add_argument("--max-writes", type=int, default=30)
    sub.add_parser("list")
    for n in ("rotate", "disable", "enable", "remove"): sub.add_parser(n).add_argument("name")
    ns = p.parse_args()
    try:
        if ns.cmd == "add":
            s = cl.add(ns.name, [r.strip() for r in ns.repos.split(",") if r.strip()], ns.read_only, ns.max_writes)
            print(f"✅ ساخته شد: {ns.name}\nآدرس اتصال برای همین اکانت Claude (فقط همین یک‌بار نشان داده می‌شود):\n{url(s)}")
        elif ns.cmd == "rotate": print("آدرس جدید:\n" + url(cl.rotate(ns.name)))
        elif ns.cmd in ("disable", "enable"): cl.set_flag(ns.name, disabled=ns.cmd == "disable"); print("انجام شد")
        elif ns.cmd == "remove": cl.remove(ns.name); print("حذف شد")
        else:
            for c in cl.all():
                print(f"{c.name:15} prefix={c.prefix:22} repos={','.join(c.repos) or 'همه'} {'READ-ONLY ' if c.read_only else ''}{'DISABLED' if c.disabled else 'active'}")
    except ValueError as e:
        print("خطا:", e); return 1
    return 0


sys.exit(main())
