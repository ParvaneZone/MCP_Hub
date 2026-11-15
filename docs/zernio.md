# Zernio در mcp-hub

Zernio (zernio.com) یک API واحد برای انتشار روی شبکه‌های اجتماعی است. در این پروژه **آپلودر اصلی ریل اینستاگرام** است و upload-post فقط پشتیبان (fallback) است.

مستندات رسمی: https://docs.zernio.com — تغییرات: https://docs.zernio.com/changelog — وضعیت سرویس: https://status.zernio.com

## تنظیمات (`.env`)

| متغیر | توضیح |
|---|---|
| `ZERNIO_API_KEY` | کلید API (هدر `Authorization: Bearer ...`) |
| `ZERNIO_ACCOUNT_ID` | `accountId` اکانت اینستاگرام داخل Zernio |
| `ZERNIO_BASE` | پیش‌فرض `https://zernio.com/api/v1` |

اگر `ZERNIO_API_KEY` یا `ZERNIO_ACCOUNT_ID` خالی باشد، Zernio غیرفعال است و مستقیم upload-post استفاده می‌شود.

## روند انتشار (`app/zernio.py`)

1. `POST /v1/media/presign` با `filename` و `contentType` ← پاسخ: `uploadUrl` و `publicUrl`
2. `PUT` فایل روی `uploadUrl` (بدون هدر Authorization)
3. `POST /v1/posts` با `mediaItems` (آدرس `publicUrl`)، `platforms` و `publishNow: true`
4. اگر اینستاگرام آسنکرون منتشر کند، وضعیت پست با `GET /v1/posts/{id}` حداکثر ~۲ دقیقه چک می‌شود.

نمونه‌ی بدنه‌ی پست:

```json
{
  "content": "کپشن...",
  "mediaItems": [
    {"type": "video", "url": "<publicUrl ویدیو>", "instagramThumbnail": "<publicUrl کاور>"}
  ],
  "platforms": [{"platform": "instagram", "accountId": "acc_xxx"}],
  "publishNow": true
}
```

### قانون جلوگیری از پست تکراری

- اگر Zernio خطا بدهد (`ZernioError`)، ارسال با upload-post امتحان می‌شود.
- اگر پست ساخته شده ولی هنوز در حال پردازش است (`pending`)، **هرگز** به upload-post رفته نمی‌شود، چون ممکن است ریل دوبار منتشر شود.

## کاور (تامنیل) ریل

فیلد `instagramThumbnail` داخل هر آیتم `mediaItems` آدرس عمومی تصویر کاور ریل اینستاگرام است. طبق مستندات Zernio ترتیب اولویت این است:

`mediaItems[].instagramThumbnail` ← `platformSpecificData.instagramThumbnail` ← `platformSpecificData.reelCover` ← `platformSpecificData.thumbnailUrl` (قدیمی)

تصویر کاور هم با همان `presign` آپلود می‌شود (`contentType: image/jpeg`). حداکثر حجم ۱۰ مگابایت و فرمت JPG/PNG توصیه شده است.

### فرستادن کاور از طریق ربات تلگرام

1. بعد از ساخت ریل، پیش‌نمایش ویدیو در تلگرام می‌آید.
2. یک عکس بفرست و آن را روی **پیام پیش‌نمایش ویدیو Reply** کن (عکس معمولی یا فایل تصویری، هر دو قبول است).
3. راه‌های دیگر: در کپشن عکس شناسه‌ی ریل را بنویس (مثلاً `#ab12cd34`)، یا اگر فقط یک ریل در انتظار تأیید باشد همان انتخاب می‌شود.
4. ربات تأیید می‌دهد. عکس جدید جای کاور قبلی را می‌گیرد.
5. با زدن «تأیید و ارسال»، کاور همراه ویدیو در Zernio آپلود و منتشر می‌شود.

تصویر خودکار به ۱۰۸۰×۱۹۲۰ (نسبت ۹:۱۶) برش مرکزی می‌خورد و به JPEG تبدیل می‌شود. اگر نمی‌خواهی برش بخورد، تصویر را از قبل با نسبت ۹:۱۶ بفرست.

اگر آپلود کاور به Zernio ناموفق باشد، ریل بدون کاور سفارشی منتشر می‌شود و در تلگرام هشدار می‌آید. مسیر upload-post کاور سفارشی را اعمال نمی‌کند.

## خطاها

پاسخ‌های 4xx/5xx از Zernio به‌صورت JSON با فیلدهای `code` و `error` هستند. متن خطا همراه کد HTTP در تلگرام نشان داده می‌شود.

## ابزارهای دیگر Zernio

- MCP رسمی: `https://mcp.zernio.com/mcp`
- SDKها: Node، Python، Go، Ruby، Java، PHP، .NET، Rust
- CLI: `npm install -g @zernio/cli`
