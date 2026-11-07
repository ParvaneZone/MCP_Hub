#!/usr/bin/env bash
# منوی مدیریت mcp-hub.   اجرا:  mcp-hub   (یا:  bash menu.sh)
# دستورهای سریع بدون منو:  mcp-hub status | url | update | backup | logs | accounts [دستور]
set -u

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
ENV_FILE="${MCP_HUB_ENV:-$DIR/.env}"
BACKUP_DIR="${MCP_HUB_BACKUPS:-/root/mcp-hub-backups}"

if [ -t 1 ]; then
  C_OK=$'\e[32m'; C_ERR=$'\e[31m'; C_HEAD=$'\e[1;36m'; C_OFF=$'\e[0m'
else
  C_OK=''; C_ERR=''; C_HEAD=''; C_OFF=''
fi

ok()      { printf '%s✔ %s%s\n' "$C_OK" "$*" "$C_OFF"; }
err()     { printf '%s✘ %s%s\n' "$C_ERR" "$*" "$C_OFF" >&2; }
title()   { printf '\n%s== %s ==%s\n' "$C_HEAD" "$*" "$C_OFF"; }
pause()   { if [ -t 0 ]; then read -r -p "Enter برای ادامه… " _; fi; }
confirm() { local a; read -r -p "$1 [y/N] " a; [ "$a" = y ] || [ "$a" = Y ]; }

dc() { (cd "$DIR" && docker compose "$@"); }

# ---------- خواندن/نوشتن .env ----------
get_env() {
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-
}

set_env() {
  local k="$1" v="$2" tmp
  [ -f "$ENV_FILE" ] || : > "$ENV_FILE"
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  if grep -qE "^$k=" "$ENV_FILE"; then
    V="$v" awk -v k="$k" 'BEGIN{FS=OFS="="} $1==k{print k "=" ENVIRON["V"]; next} {print}' "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"
    if [ -s "$tmp" ] && [ -n "$(tail -c1 "$tmp")" ]; then echo >> "$tmp"; fi
    printf '%s=%s\n' "$k" "$v" >> "$tmp"
  fi
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
}

# ---------- ریپوهای مجاز (ALLOWED_REPOS) ----------
repos_list() {
  get_env ALLOWED_REPOS | tr ',' '\n' | sed 's/^ *//;s/ *$//' | grep -v '^$'
}

repos_add() {
  local r="$1" cur new
  if ! [[ "$r" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    err "فرمت باید Owner/Repo باشد"; return 1
  fi
  if repos_list | grep -ixF -- "$r" >/dev/null; then
    echo "از قبل در لیست است"; return 0
  fi
  cur="$(repos_list | paste -sd, -)"
  new="${cur:+$cur,}$r"
  set_env ALLOWED_REPOS "$new"
}

repos_remove() {
  local r="$1" new
  new="$(repos_list | grep -vixF -- "$r" | paste -sd, -)"
  set_env ALLOWED_REPOS "$new"
}

apply_env() {
  echo "اعمال تغییرات (ساخت دوباره‌ی کانتینر hub)…"
  dc up -d --force-recreate hub
}

editor() { command -v "${EDITOR:-nano}" >/dev/null 2>&1 && echo "${EDITOR:-nano}" || echo vi; }

# ---------- وضعیت ----------
health() {
  local rc=0 s
  if dc exec -T hub python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8787/health',timeout=5)" >/dev/null 2>&1; then
    ok "سرویس داخلی سالم است"
  else
    err "سرویس داخلی جواب نمی‌دهد"; rc=1
  fi
  s="$(get_env SITE_ADDR)"
  if [ -z "$s" ]; then
    err "SITE_ADDR در .env خالی است"; rc=1
  elif curl -fsS --max-time 15 "https://$s/health" >/dev/null 2>&1; then
    ok "آدرس عمومی کار می‌کند: https://$s"
  else
    err "آدرس عمومی جواب نمی‌دهد (DNS و پورت 443 را بررسی کن): https://$s"; rc=1
  fi
  return $rc
}

menu_status() { title "وضعیت و سلامت"; dc ps; echo; health; }

show_url() {
  local s k
  title "آدرس اتصال Claude (اکانت default)"
  s="$(get_env SITE_ADDR)"; k="$(get_env MCP_SECRET)"
  if [ -z "$s" ] || [ -z "$k" ]; then err "SITE_ADDR یا MCP_SECRET در .env خالی است"; return 1; fi
  echo "https://$s/$k/mcp"
  echo "این آدرس مثل رمز است؛ جایی منتشرش نکن."
}

# ---------- اکانت‌های Claude ----------
manage() { dc exec -T -e PUBLIC_HOST="$(get_env SITE_ADDR)" hub python manage.py "$@"; }

valid_name() { [[ "$1" =~ ^[A-Za-z0-9_-]{2,30}$ ]]; }

account_add() {
  local name repos ro mw args
  read -r -p "نام اکانت (انگلیسی، مثل team-a): " name
  valid_name "$name" || { err "نام باید 2 تا 30 حرف انگلیسی/عدد/خط‌تیره باشد"; return 1; }
  echo "ریپوهای مجاز این اکانت (خالی = همه‌ی ریپوهای مجاز سرور):"
  read -r -p "مثلاً Owner/RepoA,Owner/RepoB : " repos
  read -r -p "فقط‌خواندنی؟ [y/N] " ro
  read -r -p "سقف نوشتن در ساعت [30]: " mw
  mw="${mw:-30}"
  [[ "$mw" =~ ^[0-9]+$ ]] || { err "عدد معتبر نیست"; return 1; }
  args=(add "$name" --max-writes "$mw")
  if [ -n "$repos" ]; then args+=(--repos "$repos"); fi
  case "$ro" in y|Y) args+=(--read-only);; esac
  manage "${args[@]}"
  echo
  echo "آدرس بالا را همین الان کپی کن؛ دوباره نشان داده نمی‌شود."
}

account_act() {
  local name
  manage list
  read -r -p "نام اکانت: " name
  valid_name "$name" || { err "نام نامعتبر"; return 1; }
  case "$1" in
    3) manage rotate "$name";;
    4) manage disable "$name";;
    5) manage enable "$name";;
    6) if confirm "اکانت $name حذف شود؟"; then manage remove "$name"; fi;;
  esac
}

menu_accounts() {
  local c
  while true; do
    title "اکانت‌های Claude"
    cat <<'EOF'
 1) فهرست اکانت‌ها
 2) ساخت اکانت جدید
 3) آدرس جدید برای یک اکانت (آدرس قبلی باطل می‌شود)
 4) غیرفعال کردن یک اکانت
 5) فعال کردن یک اکانت
 6) حذف یک اکانت
 0) بازگشت
EOF
    read -r -p "> " c
    case "$c" in
      1) manage list; pause;;
      2) account_add; pause;;
      3|4|5|6) account_act "$c"; pause;;
      0|"") return;;
      *) err "گزینه‌ی نامعتبر";;
    esac
  done
}

# ---------- ریپوهای GitHub ----------
menu_repos() {
  local c r
  while true; do
    title "ریپوهای مجاز GitHub"
    repos_list | sed 's/^/  - /'
    cat <<'EOF'

 1) افزودن ریپو
 2) حذف ریپو
 0) بازگشت
یادآوری: توکن GitHub هم باید به ریپوی جدید دسترسی (Contents و Pull requests) داشته باشد.
EOF
    read -r -p "> " c
    case "$c" in
      1)
        read -r -p "نام ریپو (Owner/Repo): " r
        if repos_add "$r"; then ok "اضافه شد"; if confirm "الان اعمال شود؟"; then apply_env; fi; fi;;
      2)
        read -r -p "نام ریپو برای حذف: " r
        repos_remove "$r"; ok "حذف شد (اگر در لیست بود)"
        if confirm "الان اعمال شود؟"; then apply_env; fi;;
      0|"") return;;
      *) err "گزینه‌ی نامعتبر";;
    esac
  done
}

# ---------- لاگ، شروع/توقف، به‌روزرسانی ----------
menu_logs() {
  local c
  title "لاگ‌ها"
  cat <<'EOF'
 1) hub، 100 خط آخر
 2) hub، زنده (با Ctrl+C برمی‌گردی)
 3) caddy، 50 خط آخر
 0) بازگشت
EOF
  read -r -p "> " c
  case "$c" in
    1) dc logs --tail=100 hub; pause;;
    2) trap ':' INT; dc logs -f --tail=50 hub; trap - INT;;
    3) dc logs --tail=50 caddy; pause;;
  esac
}

menu_power() {
  local c
  title "شروع / توقف"
  cat <<'EOF'
 1) شروع (up)
 2) توقف
 3) ری‌استارت hub
 4) ساخت دوباره‌ی ایمیج و شروع
 0) بازگشت
EOF
  read -r -p "> " c
  case "$c" in
    1) dc up -d;;
    2) if confirm "هر دو سرویس متوقف شوند؟"; then dc stop; fi;;
    3) dc restart hub;;
    4) dc up -d --build;;
  esac
  pause
}

do_update() {
  local before after
  title "به‌روزرسانی از GitHub"
  before="$(git -C "$DIR" rev-parse --short HEAD 2>/dev/null)"
  if ! bash "$DIR/update.sh"; then err "به‌روزرسانی ناموفق بود"; return 1; fi
  after="$(git -C "$DIR" rev-parse --short HEAD 2>/dev/null)"
  if [ "$before" = "$after" ]; then
    ok "کد جدیدی نبود ($after)"
  else
    ok "$before → $after"
    git -C "$DIR" log --oneline "$before..$after" | head -10
  fi
}

edit_env() {
  local before after
  title "ویرایش تنظیمات (.env)"
  before="$(cksum < "$ENV_FILE")"
  "$(editor)" "$ENV_FILE"
  after="$(cksum < "$ENV_FILE")"
  if [ "$before" != "$after" ]; then
    if confirm "تغییرات اعمال شود؟ (hub دوباره ساخته می‌شود)"; then apply_env; fi
  else
    echo "تغییری نبود."
  fi
}

edit_rules() {
  title "قوانین Claude (config/RULES.md)"
  echo "بدون ری‌استارت اعمال می‌شود. توجه: اگر همین فایل را در GitHub هم عوض کنی، آپدیت ممکن است تداخل بدهد."
  "$(editor)" "$DIR/config/RULES.md"
}

# ---------- بکاپ ----------
do_backup() {
  local f
  mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
  f="$BACKUP_DIR/mcp-hub-$(date +%Y%m%d-%H%M%S).tar.gz"
  if tar czf "$f" -C "$DIR" --exclude='data/videos' --exclude='data/piper' data .env config; then
    chmod 600 "$f"
    ok "بکاپ ساخته شد: $f ($(du -h "$f" | cut -f1))"
    ls -1t "$BACKUP_DIR"/mcp-hub-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
  else
    err "ساخت بکاپ ناموفق بود"; return 1
  fi
}

do_restore() {
  local files=() f i=0 pick a
  mapfile -t files < <(ls -1t "$BACKUP_DIR"/mcp-hub-*.tar.gz 2>/dev/null)
  if [ "${#files[@]}" -eq 0 ]; then err "بکاپی در $BACKUP_DIR نیست"; return 1; fi
  for f in "${files[@]}"; do i=$((i + 1)); echo " $i) $(basename "$f")"; done
  read -r -p "شماره‌ی بکاپ (0 = لغو): " pick
  if ! [[ "$pick" =~ ^[0-9]+$ ]] || [ "$pick" -lt 1 ] || [ "$pick" -gt "${#files[@]}" ]; then
    echo "لغو شد"; return 0
  fi
  f="${files[$((pick - 1))]}"
  echo "هشدار: .env و data و config فعلی با محتوای این بکاپ جایگزین می‌شوند (قبلش از وضعیت فعلی هم بکاپ گرفته می‌شود)."
  read -r -p "برای ادامه yes را تایپ کن: " a
  [ "$a" = yes ] || { echo "لغو شد"; return 0; }
  do_backup || return 1
  dc stop hub
  if tar xzf "$f" -C "$DIR"; then ok "بازیابی شد"; else err "بازیابی ناموفق بود"; fi
  dc up -d hub
}

menu_backup() {
  local c
  title "بکاپ و بازیابی"
  cat <<'EOF'
 1) گرفتن بکاپ (ویدیوهای موقت و صداهای دانلودی داخلش نیست)
 2) بازیابی از بکاپ
 0) بازگشت
EOF
  read -r -p "> " c
  case "$c" in
    1) do_backup; pause;;
    2) do_restore; pause;;
  esac
}

# ---------- گزارش، دیسک، حذف ----------
show_audit() {
  title "گزارش عملیات GitHub (40 مورد آخر)"
  if [ -f "$DIR/data/audit.log" ]; then tail -n 40 "$DIR/data/audit.log"; else echo "هنوز گزارشی نیست."; fi
}

menu_disk() {
  title "فضای دیسک"
  du -sh "$DIR/data" 2>/dev/null
  docker system df
  if confirm "ایمیج‌های بلااستفاده پاک شوند؟"; then docker image prune -f; fi
}

menu_remove() {
  local a
  title "حذف سرویس"
  echo "کانتینرها حذف می‌شوند ولی فایل‌ها، .env و data می‌مانند."
  read -r -p "برای ادامه DELETE را تایپ کن: " a
  if [ "$a" = DELETE ]; then dc down; ok "کانتینرها حذف شدند. برای راه‌اندازی دوباره: cd $DIR && docker compose up -d"; else echo "لغو شد"; fi
}

usage() {
  cat <<'EOF'
mcp-hub              منوی کامل
mcp-hub status       وضعیت و سلامت
mcp-hub url          آدرس اتصال اکانت default
mcp-hub update       به‌روزرسانی از GitHub
mcp-hub backup       گرفتن بکاپ (مناسب cron)
mcp-hub logs         100 خط آخر لاگ
mcp-hub accounts [دستور manage.py]   مثلاً: mcp-hub accounts list
EOF
}

main_menu() {
  local c
  while true; do
    title "MCP Hub"
    cat <<'EOF'
  1) وضعیت و سلامت
  2) آدرس اتصال Claude
  3) اکانت‌های Claude
  4) ریپوهای مجاز GitHub
  5) لاگ‌ها
  6) شروع / توقف / ری‌استارت
  7) به‌روزرسانی از GitHub
  8) ویرایش تنظیمات (.env)
  9) ویرایش قوانین Claude
 10) بکاپ و بازیابی
 11) گزارش عملیات GitHub
 12) فضای دیسک و پاک‌سازی
 13) حذف سرویس
  0) خروج
EOF
    read -r -p "> " c
    case "$c" in
      1) menu_status; pause;;
      2) show_url; pause;;
      3) menu_accounts;;
      4) menu_repos;;
      5) menu_logs;;
      6) menu_power;;
      7) do_update; pause;;
      8) edit_env; pause;;
      9) edit_rules; pause;;
      10) menu_backup;;
      11) show_audit; pause;;
      12) menu_disk; pause;;
      13) menu_remove; pause;;
      0|q|"") exit 0;;
      *) err "گزینه‌ی نامعتبر";;
    esac
  done
}

main() {
  command -v docker >/dev/null 2>&1 || { err "docker نصب نیست"; exit 1; }
  [ -f "$DIR/docker-compose.yml" ] || { err "docker-compose.yml در $DIR نیست"; exit 1; }
  case "${1:-}" in
    status) menu_status; return;;
    url) show_url; return;;
    update) do_update; return;;
    backup) do_backup; return;;
    logs) dc logs --tail=100 hub; return;;
    accounts) shift; manage "${@:-list}"; return;;
    help|-h|--help) usage; return;;
    "") main_menu;;
    *) usage; exit 1;;
  esac
}

# وقتی فایل با source بارگذاری شود (مثلاً در تست‌ها) منو اجرا نمی‌شود.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
