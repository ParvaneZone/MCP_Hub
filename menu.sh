#!/usr/bin/env bash
# MCP Hub - terminal menu.
# Usage: mcp-hub            (interactive menu)
#        mcp-hub <command>  (setup|start|stop|restart|status|logs|update|url|accounts ...)
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
ENV_FILE="$DIR/.env"
# Compose declares these volumes as external (kept from the old reels-mcp project).
VOLUMES=(reels-mcp_caddy_data reels-mcp_caddy_config)

C_G=$'\e[32m'; C_R=$'\e[31m'; C_Y=$'\e[33m'; C_B=$'\e[1m'; C_0=$'\e[0m'
ok()    { echo "${C_G}OK${C_0} $*"; }
warn()  { echo "${C_Y}!${C_0} $*"; }
err()   { echo "${C_R}ERROR${C_0} $*" >&2; }
pause() { if [ -t 0 ]; then read -rp "Press Enter to continue..." _; fi; return 0; }
dc()    { docker compose "$@"; }

usage() {
  cat <<'EOF'
Usage: mcp-hub [command]
  (no command)   interactive menu
  setup          create / edit .env
  start          build and start (docker compose up -d --build)
  stop | restart | status | logs
  update         git pull + rebuild
  url            show the default connection URL for Claude
  accounts ...   pass-through to manage.py (list, add NAME, rotate NAME, ...)
EOF
}

check_docker() {
  command -v docker >/dev/null 2>&1 || { err "docker is not installed. Run install.sh first."; exit 1; }
  docker compose version >/dev/null 2>&1 || { err "docker compose plugin is missing."; exit 1; }
  docker info >/dev/null 2>&1 || { err "Cannot talk to the docker daemon (run as root / with sudo)."; exit 1; }
}

# ---------- .env helpers ----------
env_get() {
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^$1=" "$ENV_FILE" | tail -n1 \
    | sed -E "s/^$1=//; s/[[:space:]]+#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//"
}

env_set() {
  local k="$1" v="$2" tmp
  touch "$ENV_FILE"
  tmp="$(mktemp)"
  grep -v "^${k}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$k" "$v" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
  chmod 600 "$ENV_FILE"
}

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 16
  else
    head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

# ask KEY "Label" [s]   -> Enter keeps the current value; 3rd arg = secret input
ask() {
  local k="$1" label="$2" secret="${3:-}" cur new shown
  cur="$(env_get "$k")"
  if [ -n "$secret" ] && [ -n "$cur" ]; then shown="${cur:0:4}...(hidden)"; else shown="$cur"; fi
  if [ -n "$secret" ]; then
    read -rsp "$label [$shown]: " new; echo
  else
    read -rp "$label [$shown]: " new
  fi
  if [ -n "$new" ]; then env_set "$k" "$new"; fi
  return 0
}

public_host() {
  local h p
  h="$(env_get SITE_ADDR)"; p="$(env_get SSL_PORT)"
  if [ -n "$p" ] && [ "$p" != "443" ]; then h="$h:$p"; fi
  echo "$h"
}

check_env() {
  local miss=() k
  for k in UPLOADPOST_API_KEY UPLOADPOST_USER TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID MCP_SECRET SITE_ADDR; do
    [ -n "$(env_get "$k")" ] || miss+=("$k")
  done
  if [ "$(env_get SITE_ADDR)" = "your.domain.com" ]; then miss+=("SITE_ADDR"); fi
  if [ "${#miss[@]}" -gt 0 ]; then
    err "Missing in .env: ${miss[*]}  (run Setup first)"
    return 1
  fi
  return 0
}

ensure_volumes() {
  local v
  for v in "${VOLUMES[@]}"; do
    docker volume inspect "$v" >/dev/null 2>&1 || docker volume create "$v" >/dev/null
  done
}

is_running() { dc ps --status running --services 2>/dev/null | grep -qx hub; }

# ---------- actions ----------
setup() {
  [ -f "$ENV_FILE" ] || { : > "$ENV_FILE"; chmod 600 "$ENV_FILE"; }
  echo "${C_B}Configuration${C_0} (press Enter to keep the current value)"
  ask SITE_ADDR "Domain (A record must point to this server)"
  ask SSL_PORT "HTTPS port"
  ask UPLOADPOST_API_KEY "Upload-Post API key" s
  ask UPLOADPOST_USER "Upload-Post user"
  ask TELEGRAM_BOT_TOKEN "Telegram bot token" s
  ask TELEGRAM_CHAT_ID "Telegram chat id (owner)"
  ask GITHUB_TOKEN "GitHub fine-grained token (Contents + Pull requests: R/W)" s
  ask ALLOWED_REPOS "Allowed repos (Owner/Repo1,Owner/Repo2)"
  [ -n "$(env_get SSL_PORT)" ] || env_set SSL_PORT 443
  local sec; sec="$(env_get MCP_SECRET)"
  if [ "${#sec}" -lt 24 ]; then
    env_set MCP_SECRET "$(gen_secret)"
    ok "MCP_SECRET generated"
  fi
  ok "Saved to $ENV_FILE"
  echo "Next: point DNS of $(env_get SITE_ADDR) to this server, open ports 80 and $(env_get SSL_PORT), then choose Start."
}

show_url() {
  local s; s="$(env_get MCP_SECRET)"
  if [ -z "$s" ]; then warn "No MCP_SECRET yet. Run Setup."; return 0; fi
  echo "Default account URL (give this to Claude):"
  echo "  https://$(public_host)/$s/mcp"
}

do_start() {
  ensure_volumes
  check_env || return 1
  dc up -d --build && ok "Started" && show_url
}

do_stop()    { dc stop && ok "Stopped"; }
do_restart() { check_env || return 1; dc restart && ok "Restarted"; }

do_logs() {
  trap ':' INT
  dc logs -f --tail=100 hub
  trap - INT
}

do_status() {
  dc ps
  echo
  if is_running; then
    if curl -fsS -m 8 "https://$(public_host)/health" >/dev/null 2>&1; then
      ok "Public HTTPS health check passed"
    else
      warn "Public health check failed (DNS, ports 80/443 or the certificate may still be pending)"
    fi
  else
    warn "hub is not running"
  fi
}

do_update() {
  git pull --ff-only || { err "git pull failed"; return 1; }
  ensure_volumes
  check_env || return 1
  dc up -d --build && ok "Updated"
  docker image prune -f >/dev/null 2>&1 || true
}

manage() {
  if ! is_running; then err "hub is not running. Start it first."; return 1; fi
  dc exec -T -e PUBLIC_HOST="$(public_host)" hub python manage.py "$@"
}

accounts_menu() {
  local c n r ro mw y cmd args
  while true; do
    echo
    echo "${C_B}Accounts${C_0}"
    echo " 1) List"
    echo " 2) Add"
    echo " 3) Rotate secret"
    echo " 4) Disable"
    echo " 5) Enable"
    echo " 6) Remove"
    echo " 0) Back"
    read -rp "> " c || return 0
    case "$c" in
      1) manage list ;;
      2)
        read -rp "Name: " n
        read -rp "Repos (a/b,c/d - empty = all): " r
        read -rp "Read-only? [y/N]: " ro
        read -rp "Max writes [30]: " mw
        args=(add "$n")
        [ -n "$r" ] && args+=(--repos "$r")
        [[ "$ro" =~ ^[Yy] ]] && args+=(--read-only)
        [ -n "$mw" ] && args+=(--max-writes "$mw")
        manage "${args[@]}"
        ;;
      3|4|5|6)
        read -rp "Account name: " n
        case "$c" in 3) cmd=rotate ;; 4) cmd=disable ;; 5) cmd=enable ;; *) cmd=remove ;; esac
        if [ "$cmd" = remove ]; then
          read -rp "Remove '$n'? [y/N]: " y
          [[ "$y" =~ ^[Yy] ]] || continue
        fi
        manage "$cmd" "$n"
        ;;
      0) return 0 ;;
      *) warn "Invalid choice" ;;
    esac
  done
}

main_menu() {
  local ch
  while true; do
    clear 2>/dev/null || true
    echo "${C_B}=== MCP Hub ===${C_0}  ($DIR)"
    if is_running; then echo "Status: ${C_G}running${C_0}"; else echo "Status: ${C_R}not running${C_0}"; fi
    echo
    echo " 1) Setup / edit config (.env)"
    echo " 2) Start / rebuild"
    echo " 3) Stop"
    echo " 4) Restart"
    echo " 5) Status"
    echo " 6) Logs (Ctrl+C to return)"
    echo " 7) Update from GitHub"
    echo " 8) Accounts (list / add / rotate ...)"
    echo " 9) Show connection URL"
    echo " 0) Exit"
    echo
    read -rp "Choose: " ch || exit 0
    echo
    case "$ch" in
      1) setup ;;
      2) do_start ;;
      3) do_stop ;;
      4) do_restart ;;
      5) do_status ;;
      6) do_logs ;;
      7) do_update ;;
      8) accounts_menu ;;
      9) show_url ;;
      0|q) exit 0 ;;
      *) warn "Invalid choice" ;;
    esac
    case "$ch" in 6|8) ;; *) pause ;; esac
  done
}

case "${1:-menu}" in
  help|-h|--help) usage ;;
  *)
    check_docker
    cmd="${1:-menu}"; [ "$#" -gt 0 ] && shift
    case "$cmd" in
      menu) main_menu ;;
      setup) setup ;;
      start|up) do_start ;;
      stop|down) do_stop ;;
      restart) do_restart ;;
      status) do_status ;;
      logs) do_logs ;;
      update) do_update ;;
      url) show_url ;;
      accounts) manage "$@" ;;
      *) usage; exit 1 ;;
    esac
    ;;
esac
