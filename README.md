# News Manager Bot (نسخه پایتون) 🤖📰

یک سیستم خودکار و ماژولار برای مانیتورینگ، استخراج، بازنویسی هوشمند و انتشار اخبار در کانال‌های تلگرام، توسعه داده شده با **Python** و فریم‌ورک **python-telegram-bot (v21+)**.

این پروژه نسخه بازنویسی شده و ارتقا یافته ریپازیتوری [news-manager-bot](https://github.com/usghloasytaso/news-manager-bot) به زبان پایتون است.

---

## 🌟 ویژگی‌های کلیدی

- **اسکرپر پیشرفته کانال‌ها (Telethon MTProto):** مانیتورینگ مداوم کانال‌های مبدا عمومی و خصوصی بدون نیاز به دسترسی ادمین.
- **احراز هویت آسان با QR Code:** اتصال سریع اکانت تلگرام از طریق ارسال کد QR به پیوی ادمین در ربات همراه با پشتیبانی از تایید دو مرحله‌ای (2FA).
- **بازنویسی هوشمند اخبار با 9router:** ادغام کامل با سرویس و گیت‌وی 9router با پشتیبانی از مدل‌های روز (مانند `gemini/gemini-3.5-flash-lite`، LLaMA 3.3، Claude و غیره).
- **پالایش خودکار و حذف تبلیغات:** پاک‌سازی تمامی آیدی‌ها، لینک‌های اسپانسر، پیام‌های تبلیغاتی و ترجمه اخبار خارجی به فارسی روان و استاندارد مطبوعاتی.
- **مدیریت کامل رسانه (عکس و ویدیو):** دانلود رسانه‌های همراه خبر و ارسال آن‌ها با کپشن فارسی هوش مصنوعی همراه با امکان فعال/غیرفعال‌سازی از پنل ادمین.
- **پایگاه داده ابری Supabase:** ذخیره‌سازی تنظیمات، صف پردازش اخبار (`nm_queue`) و جلوگیری از انتشار خبرهای تکراری با الگوریتم هشینگ (`nm_hashes`).
- **پنل ادمین شیشه‌ای (Inline Keyboards):** کنترل لحظه‌ای وضعیت ربات، اسکن دستی، انتشار دستی، تغییر کانال مقصد، امضا و فواصل زمانی اسکن.
- **وب‌سرور داخلی Health Check:** پشتیبانی از مسیرهای `/` و `/health` جهت جلوگیری از به خواب رفتن ربات در سرورهای رایگان (مانند Render و Railway).

---

## 📁 ساختار پروژه

```text
news_manager_bot/
├── bot/
│   ├── handlers.py          # مدیریت دستورات، پیام‌ها و کالبک‌های ادمین
│   └── keyboards.py         # کیبوردهای شیشه‌ای منو و تنظیمات
├── ai_service.py            # اتصال به 9router و پرامپت خبرنگاری فارسی
├── config.py                # مدیریت متغیرهای محیطی و تنظیمات پیش‌فرض
├── database.py              # لایه ارتباطی با دیتابیس Supabase
├── engine.py                # موتور اسکن، هشینگ محتوا، صف و انتشار
├── main.py                  # نقطه ورود اصلی و اجرای هم‌زمان ورکر و ربات
├── user_client.py           # کلاینت Telethon برای اسکرپ کانال‌ها و ورود با QR
├── web_server.py            # سرور aiohttp برای بررسی سلامت سرویس
├── requirements.txt         # نیازمندی‌های پایتون
├── schema.sql               # ساختار جداول دیتابیس Supabase
├── .env.example             # نمونه مقادیر متغیرهای محیطی
└── README.md
```

---

## 🚀 راهنمای نصب و راه‌اندازی

### ۱. پیش‌نیازها
- پایتون نسخه 3.10 یا بالاتر
- توکن ربات تلگرام از [BotFather](https://t.me/BotFather)
- شناسه و هش تلگرام (`API_ID` و `API_HASH`) از [my.telegram.org](https://my.telegram.org)
- پروژه رایگان در [Supabase](https://supabase.com)
- سرویس [9router](https://github.com/decolua/9router) در حال اجرا (پیش‌فرض روی `http://localhost:20128/v1`)

### ۲. تنظیم پایگاه داده در Supabase
وارد داشبورد Supabase خود شده و در بخش **SQL Editor**، کدهای فایل `schema.sql` را اجرا کنید:

```sql
CREATE TABLE IF NOT EXISTS nm_kv (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nm_hashes (
    hash TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nm_queue (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    msg_id BIGINT NOT NULL,
    text TEXT,
    media_type TEXT,
    media_file_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nm_queue_status_id ON nm_queue(status, id);
CREATE INDEX IF NOT EXISTS idx_nm_hashes_hash ON nm_hashes(hash);
```

### ۳. نصب پکیج‌ها
```bash
git clone https://github.com/your-username/news-manager-bot.git
cd news-manager-bot
python3 -m venv venv
source venv/bin/activate  # در ویندوز: venv\Scripts\activate
pip install -r requirements.txt
```

### ۴. پیکربندی متغیرهای محیطی
فایل `.env.example` را به `.env` تغییر نام داده و اطلاعات خود را وارد کنید:

```env
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
ADMIN_ID=123456789
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-or-service-role-key
NINEROUTER_BASE_URL=http://localhost:20128/v1
NINEROUTER_API_KEY=sk-9router
NINEROUTER_MODEL=gemini/gemini-3.5-flash-lite
PORT=8080
```

### ۵. اجرای پروژه
```bash
python3 main.py
```

---

## 📱 مراحل اتصال و شروع به کار

1. در تلگرام وارد ربات خود شوید و دستور `/start` را ارسال کنید.
2. از منوی اصلی، روی دکمه **«📱 ورود / اتصال اکانت (QR)»** کلیک کنید.
3. کد QR ارسالی در چت را با استفاده از تلگرام گوشی خود در مسیر `Settings > Devices > Link Desktop Device` اسکن کنید (اگر اکانت دارای رمز دومرحله‌ای باشد، ربات رمز را از شما خواهد پرسید).
4. با استفاده از دکمه **«📋 مدیریت کانال‌های مبدا»**، کانال‌های خبری مدنظرتان را اضافه کنید.
5. ربات خود را به عنوان **ادمین (با دسترسی ارسال پیام)** در کانال مقصد عضو کنید و با دکمه **«📢 کانال مقصد»** آیدی آن را ثبت کنید.
6. در نهایت دکمه **«وضعیت ربات»** را روی حالت روشن قرار دهید تا فرآیند مانیتورینگ و انتشار خودکار آغاز شود.
