# mcp-hub

یک سرور MCP واحد: ابزارهای ساخت Reel اینستاگرام + ابزارهای نوشتن روی GitHub.
آدرس برای Claude: `https://<SITE_ADDR>/<راز-اکانت>/mcp`

## نصب روی سرور (Ubuntu/Debian، با کاربر root)

پیش‌نیاز: یک دامنه که رکورد A آن به IP سرور اشاره کند و پورت‌های 80 و 443 باز باشند.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ParvaneZone/MCP_Hub/main/install.sh)
```

این دستور در صورت نبودن git و docker آن‌ها را نصب می‌کند، پروژه را در `/opt/mcp-hub` کلون می‌کند، دستور `mcp-hub` را می‌سازد و منوی ترمینال را باز می‌کند.
در منو اول گزینه‌ی 1 (Setup) برای وارد کردن تنظیمات و بعد گزینه‌ی 2 (Start) را بزنید. آدرس اتصال برای Claude با گزینه‌ی 9 نشان داده می‌شود.

اگر ریپو private است، دستور بالا کار نمی‌کند؛ دستی کلون کنید:

```bash
git clone https://github.com/ParvaneZone/MCP_Hub.git /opt/mcp-hub && bash /opt/mcp-hub/install.sh
```

## استفاده

بعد از نصب فقط بنویسید `mcp-hub` تا منو باز شود. دستورهای مستقیم:

| دستور | کار |
|---|---|
| `mcp-hub setup` | ساخت/ویرایش `.env` |
| `mcp-hub start` | ساخت و اجرا |
| `mcp-hub stop` / `restart` / `status` / `logs` | مدیریت سرویس |
| `mcp-hub update` | `git pull` و بیلد دوباره |
| `mcp-hub url` | نشان دادن آدرس اتصال اکانت default |
| `mcp-hub accounts list` | مدیریت اکانت‌ها (add، rotate، disable، enable، remove) |

راه دستی هم هنوز کار می‌کند:
اکانت‌های بیشتر: `docker compose exec hub python manage.py` (راهنما را نشان می‌دهد).
به‌روزرسانی: `./update.sh`
