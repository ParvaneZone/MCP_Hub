#!/usr/bin/env bash
# MCP Hub installer (Debian/Ubuntu). Run as root:
#   bash <(curl -fsSL https://raw.githubusercontent.com/ParvaneZone/MCP_Hub/main/install.sh)
# Installs git/curl/docker if missing, clones the repo to /opt/mcp-hub,
# creates the `mcp-hub` command and opens the terminal menu.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ParvaneZone/MCP_Hub.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/mcp-hub}"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root (use: sudo -i)."

# If this script is run from inside an existing clone, use that clone.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/docker-compose.yml" ] && [ -f "$SELF_DIR/menu.sh" ]; then
  INSTALL_DIR="$SELF_DIR"
fi

missing=""
for c in git curl openssl; do
  command -v "$c" >/dev/null 2>&1 || missing="$missing $c"
done
if [ -n "$missing" ]; then
  command -v apt-get >/dev/null 2>&1 || die "Install these first:$missing"
  say "Installing:$missing"
  apt-get update -y
  apt-get install -y ca-certificates $missing
fi

if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker compose version >/dev/null 2>&1 || die "docker compose plugin is missing (install docker-compose-plugin)."

if [ -d "$INSTALL_DIR/.git" ]; then
  say "Updating $INSTALL_DIR"
  git -C "$INSTALL_DIR" pull --ff-only
else
  if [ -d "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    die "$INSTALL_DIR already exists and is not empty."
  fi
  say "Cloning $REPO_URL to $INSTALL_DIR"
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR" \
    || die "Clone failed. If the repo is private, clone it manually, then run: bash $INSTALL_DIR/install.sh"
fi

# Small wrapper so the command works without chmod (keeps git file modes clean).
cat > /usr/local/bin/mcp-hub <<WRAP
#!/usr/bin/env bash
exec bash "$INSTALL_DIR/menu.sh" "\$@"
WRAP
chmod +x /usr/local/bin/mcp-hub

say "Installed. From now on just run: mcp-hub"
echo "Reminder: point your domain's DNS A record to this server and open ports 80 and 443 (or your SSL_PORT)."

if [ -r /dev/tty ]; then
  exec bash "$INSTALL_DIR/menu.sh" </dev/tty
fi
exec bash "$INSTALL_DIR/menu.sh"
