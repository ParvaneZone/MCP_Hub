"""MCP Hub: ابزارهای ریلز اینستاگرام + گیت‌هاب در یک سرور و یک آدرس.

کد هر دو پروژه بدون تغییر استفاده می‌شود:
  app/server.py  -> ابزارهای ریلز (create_reel, reel_status, list_reels, cancel_reel)
  ghserver.py    -> ابزارهای گیت‌هاب + احراز هویت چنداکانتی (/<راز-اکانت>/mcp)
"""
import logging
import sys
import threading

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app import config, db, telegram_bot as bot
from app import server as reels
import ghserver as gh

INSTRUCTIONS = (
    "This server has two toolsets. Instagram Reels tools: create_reel, reel_status, list_reels, cancel_reel. "
    "GitHub tools: get_rules, list_repos, list_files, read_file, create_branch, write_files, open_pull_request. "
    "Use each toolset only for its own purpose.\n\n"
    "[Reels]\n" + (getattr(reels.mcp, "instructions", None) or "") + "\n\n"
    "[GitHub]\n" + gh.INSTRUCTIONS
)

hub = FastMCP(
    "hub",
    instructions=INSTRUCTIONS,
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

TOOLS = [
    reels.create_reel, reels.reel_status, reels.list_reels, reels.cancel_reel,
    gh.get_rules, gh.list_repos, gh.list_files, gh.read_file,
    gh.create_branch, gh.write_files, gh.open_pull_request,
]
for fn in TOOLS:
    hub.add_tool(fn)

# /<راز-اکانت>/mcp  ->  شناسایی اکانت، سپس MCP. هر مسیر دیگر 404؛ /health آزاد است.
app = gh.SecretPath(hub.streamable_http_app(), gh.CLIENTS)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    miss = config.missing()
    if miss:
        sys.exit("Missing env: " + ", ".join(miss))
    db.init()
    threading.Thread(target=bot.run, daemon=True, name="telegram").start()
    logging.getLogger("hub").info("tools: %s", ", ".join(t.__name__ for t in TOOLS))
    uvicorn.run(app, host="0.0.0.0", port=config.LISTEN_PORT, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
