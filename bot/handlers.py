import asyncio
import logging
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from config import config
from database import db
from user_client import user_client_manager
from engine import engine
from bot.keyboards import (
    get_main_menu_keyboard,
    get_sources_keyboard,
    get_back_keyboard,
    get_users_management_keyboard,
    get_back_users_keyboard,
)

logger = logging.getLogger(__name__)


async def safe_edit_message(query, text: str, reply_markup=None, parse_mode: str = "Markdown"):
    """
    ویرایش امن پیام برای جلوگیری از خطای Message is not modified تلگرام
    """
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            logger.warning(f"Error editing message: {e}")
    except Exception as e:
        logger.error(f"Unexpected error editing message: {e}")


async def render_dashboard_text(user_id: int) -> str:
    settings = await db.get_user_settings(user_id)
    is_auth = await user_client_manager.is_authorized(user_id)
    user_info = await user_client_manager.get_me(user_id) if is_auth else None

    if is_auth and user_info:
        account_status = f"🟢 متصل ({getattr(user_info, 'first_name', 'کاربر')})"
    else:
        account_status = "🔴 متصل نیست (نیاز به اسکن QR)"

    dest_display = settings.dest_channel if settings.dest_channel else "تنظیم نشده ⚠️"
    sig_display = settings.signature if settings.signature else "بدون امضا"
    sources_count = len(settings.sources)
    status_badge = "🟢 فعال (روشن)" if settings.running else "🔴 متوقف (خاموش)"
    photo_badge = "✅ فعال" if settings.send_photo else "❌ غیرفعال"
    video_badge = "✅ فعال" if settings.send_video else "❌ غیرفعال"

    text = (
        "⚡ **مرکز کنترل و مدیریت اخبار اختصاصی** ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **وضعیت پنل شما:** {status_badge}\n"
        f"👤 **وضعیت اکانت اسکرپر:** {account_status}\n"
        f"📢 **کانال مقصد:** `{dest_display}`\n"
        f"✍️ **امضای پایانی:** `{sig_display}`\n"
        f"⏱ **دوره اسکن:** هر `{settings.interval_min}` دقیقه یک‌بار\n"
        f"📡 **منابع فعال شما:** `{sources_count}` کانال\n"
        f"🖼 **ارسال عکس:** {photo_badge} | 🎥 **ارسال ویدیو:** {video_badge}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 *جهت اعمال تنظیمات و عملیات، از دکمه‌های زیر استفاده کنید:*"
    )
    return text


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_user_authorized(user_id):
        await update.effective_message.reply_text(
            f"⛔ شما دسترسی لازم برای استفاده از این ربات را ندارید.\n\n"
            f"شناسه کاربری شما: `{user_id}`\n"
            "جهت دریافت دسترسی، شناسه خود را برای مالک ربات ارسال نمایید.",
            parse_mode="Markdown",
        )
        return

    context.user_data["state"] = None
    settings = await db.get_user_settings(user_id)
    text = await render_dashboard_text(user_id)
    is_owner = (user_id == config.owner_id)
    keyboard = get_main_menu_keyboard(settings.running, settings.send_photo, settings.send_video, is_owner=is_owner)

    msg = await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    context.user_data["menu_msg_id"] = msg.message_id


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if not await db.is_user_authorized(user_id):
        await query.answer("⛔ دسترسی شما مجاز نیست.", show_alert=True)
        return

    await query.answer()
    data = query.data
    settings = await db.get_user_settings(user_id)
    is_owner = (user_id == config.owner_id)
    context.user_data["menu_msg_id"] = query.message.message_id

    # بازگشت به منوی اصلی
    if data == "main_menu":
        context.user_data["state"] = None
        text = await render_dashboard_text(user_id)
        keyboard = get_main_menu_keyboard(settings.running, settings.send_photo, settings.send_video, is_owner=is_owner)
        await safe_edit_message(query, text, reply_markup=keyboard)

    # تغییر وضعیت روشن/خاموش
    elif data == "toggle_running":
        settings.running = not settings.running
        await db.save_user_settings(user_id, settings)
        text = await render_dashboard_text(user_id)
        keyboard = get_main_menu_keyboard(settings.running, settings.send_photo, settings.send_video, is_owner=is_owner)
        await safe_edit_message(query, text, reply_markup=keyboard)

    # تغییر وضعیت ارسال عکس
    elif data == "toggle_photo":
        settings.send_photo = not settings.send_photo
        await db.save_user_settings(user_id, settings)
        text = await render_dashboard_text(user_id)
        keyboard = get_main_menu_keyboard(settings.running, settings.send_photo, settings.send_video, is_owner=is_owner)
        await safe_edit_message(query, text, reply_markup=keyboard)

    # تغییر وضعیت ارسال ویدیو
    elif data == "toggle_video":
        settings.send_video = not settings.send_video
        await db.save_user_settings(user_id, settings)
        text = await render_dashboard_text(user_id)
        keyboard = get_main_menu_keyboard(settings.running, settings.send_photo, settings.send_video, is_owner=is_owner)
        await safe_edit_message(query, text, reply_markup=keyboard)

    # اسکن دستی
    elif data == "scan_now":
        if not settings.sources:
            await safe_edit_message(
                query,
                "⚠️ لیست منابع شما خالی است! لطفاً ابتدا از بخش «مدیریت کانال‌های مبدا» حداقل یک کانال اضافه کنید.",
                reply_markup=get_back_keyboard(),
            )
            return

        await safe_edit_message(query, "🔄 در حال شروع اسکن منابع خبری اختصاصی شما... لطفاً کمی صبر کنید.")
        queued_count = await engine.scan_user_sources(user_id)
        await safe_edit_message(
            query,
            f"✅ اسکن پایان یافت.\nتعداد `{queued_count}` خبر جدید به صف اختصاصی شما افزوده شد.",
            reply_markup=get_back_keyboard(),
        )

    # انتشار فوری
    elif data == "publish_now":
        if not settings.dest_channel:
            await safe_edit_message(
                query,
                "⚠️ کانال مقصد شما تنظیم نشده است! لطفاً ابتدا از بخش «کانال مقصد» آیدی کانال خود را ثبت کنید.",
                reply_markup=get_back_keyboard(),
            )
            return

        await safe_edit_message(query, "🚀 در حال پردازش و انتشار خبر بعدی از صف اختصاصی شما...")
        success = await engine.publish_user_tick(user_id, context.bot)
        if success:
            await safe_edit_message(
                query,
                "✅ یک خبر با موفقیت بازنویسی و در کانال مقصد شما منتشر شد.",
                reply_markup=get_back_keyboard(),
            )
        else:
            await safe_edit_message(
                query,
                "ℹ️ صف اخبار شما خالی است یا تنظیمات کانال بررسی نشده است.",
                reply_markup=get_back_keyboard(),
            )

    # ورود با QR
    elif data == "qr_login":
        await safe_edit_message(
            query,
            "⏳ در حال تولید کد QR جهت اتصال اکانت تلگرام شما... تصویر QR تا چند لحظه دیگر ارسال می‌شود."
        )

        async def on_qr(qr_buf):
            await context.bot.send_photo(
                chat_id=user_id,
                photo=qr_buf,
                caption=(
                    "📱 **اسکن کد QR جهت اتصال اکانت شما**\n\n"
                    "۱. در تلگرام به `Settings > Devices > Link Desktop Device` بروید.\n"
                    "۲. دوربین را مقابل این کد QR بگیرید.\n"
                    "۳. مهلت اسکن: ۱۲۰ ثانیه."
                ),
                parse_mode="Markdown",
            )

        async def on_success(user):
            text = f"✅ اتصال با موفقیت انجام شد:\nنام اکانت: {getattr(user, 'first_name', 'User')}"
            keyboard = get_main_menu_keyboard(settings.running, settings.send_photo, settings.send_video, is_owner=is_owner)
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)

        async def on_2fa():
            context.user_data["state"] = "WAITING_FOR_2FA"
            await context.bot.send_message(
                chat_id=user_id,
                text="🔐 اکانت شما دارای رمز دومرحله‌ای (2FA) است.\nلطفاً رمز عبور را ارسال کنید:",
            )

        async def on_timeout():
            await context.bot.send_message(chat_id=user_id, text="⏰ مهلت اسکن کد QR به پایان رسید.")

        async def on_error(err):
            await context.bot.send_message(chat_id=user_id, text=f"❌ خطا در ورود: {err}")

        asyncio.create_task(
            user_client_manager.start_qr_login(
                user_id=user_id,
                on_qr_generated=on_qr,
                on_success=on_success,
                on_2fa_needed=on_2fa,
                on_timeout=on_timeout,
                on_error=on_error,
            )
        )

    # منوی منابع
    elif data == "menu_sources":
        if settings.sources:
            text = (
                "📋 **لیست کانال‌های مبدا شما:**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "جهت حذف هر کانال روی 🔴 حذف مقابل آن بزنید یا با دکمه 🟢 کانال جدید اضافه کنید."
            )
        else:
            text = (
                "📋 **لیست کانال‌های مبدا شما خالی است.**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "جهت شروع مانیتورینگ، با زدن دکمه زیر کانال‌های دلخواه خود را اضافه کنید:"
            )
        keyboard = get_sources_keyboard(settings.sources)
        await safe_edit_message(query, text, reply_markup=keyboard)

    elif data == "add_source":
        context.user_data["state"] = "WAITING_FOR_SOURCE"
        await safe_edit_message(
            query,
            "➕ لطفاً آیدی کانال جدید (مانند `@MyChannel` یا آیدی عددی کانال خصوصی) را ارسال کنید:",
            reply_markup=get_back_keyboard(),
        )

    elif data.startswith("del_src_"):
        idx = int(data.replace("del_src_", ""))
        if 0 <= idx < len(settings.sources):
            removed = settings.sources.pop(idx)
            await db.save_user_settings(user_id, settings)
            text = f"🗑 کانال `{removed}` از لیست منابع شما حذف شد."
            keyboard = get_sources_keyboard(settings.sources)
            await safe_edit_message(query, text, reply_markup=keyboard)

    # کانال مقصد
    elif data == "menu_dest":
        context.user_data["state"] = "WAITING_FOR_DEST"
        current_dest = settings.dest_channel if settings.dest_channel else "هنوز تنظیمی ثبت نشده"
        await safe_edit_message(
            query,
            f"📢 **کانال مقصد فعلی:** `{current_dest}`\n\n"
            "لطفاً آیدی کانال مقصد خود (مانند `@MyNewsChannel` یا آیدی عددی `-100...`) را ارسال کنید:\n"
            "*(توجه: ربات باید در کانال مقصد ادمین با دسترسی ارسال پیام باشد)*",
            reply_markup=get_back_keyboard(),
        )

    # امضای خبر
    elif data == "menu_sig":
        context.user_data["state"] = "WAITING_FOR_SIG"
        current_sig = settings.signature if settings.signature else "بدون امضا"
        await safe_edit_message(
            query,
            f"✍️ **امضای فعلی اخبار شما:**\n`{current_sig}`\n\n"
            "لطفاً متن یا آیدی جدید امضای انتهای پست‌ها را ارسال کنید:\n"
            "*(جهت خالی کردن امضا، عبارت `None` را بفرستید)*",
            reply_markup=get_back_keyboard(),
        )

    # فاصله اسکن
    elif data == "menu_interval":
        context.user_data["state"] = "WAITING_FOR_INTERVAL"
        await safe_edit_message(
            query,
            f"⏱ **فاصله اسکن فعلی شما:** `{settings.interval_min}` دقیقه\n\n"
            "لطفاً عدد جدید فاصله اسکن را به دقیقه ارسال کنید (مثلاً `3` یا `5`):",
            reply_markup=get_back_keyboard(),
        )

    # آمار
    elif data == "menu_stats":
        stats = await db.get_queue_stats(user_id)
        text = (
            "📊 **آمار پردازش اخبار در پنل شما**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏳ در صف انتظار (Pending): `{stats.get('pending', 0)}`\n"
            f"🚀 منتشر شده (Published): `{stats.get('published', 0)}`\n"
            f"🚫 فیلتر شده توسط AI (Rejected): `{stats.get('rejected', 0)}`\n"
            f"⚠️ خطای ارسال (Failed): `{stats.get('failed', 0)}`\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await safe_edit_message(query, text, reply_markup=get_back_keyboard())

    # راهنما
    elif data == "menu_help":
        text = (
            "📖 **راهنمای استفاده از پنل اختصاصی**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "۱. ابتدا از طریق دکمه «📱 ورود / اتصال اکانت (QR)» اکانت تلگرام خود را متصل کنید.\n"
            "۲. ربات را به کانال مقصد خود اضافه کرده و ادمین کنید، سپس آیدی آن را در بخش «📢 کانال مقصد» وارد کنید.\n"
            "۳. کانال‌های خبری مدنظر خود را از طریق «📋 مدیریت کانال‌های مبدا» وارد کنید.\n"
            "۴. در صورت تمایل امضای انتهای خبرها را تنظیم نمایید.\n"
            "۵. در نهایت با زدن دکمه اول، وضعیت ربات را روی **🟢 روشن** قرار دهید تا اسکن و انتشار خودکار انجام شود."
        )
        await safe_edit_message(query, text, reply_markup=get_back_keyboard())

    # بخش مالک: مدیریت کاربران
    elif data == "menu_users":
        if not is_owner:
            await query.answer("⛔ این بخش منحصراً برای مالک اصلی ربات است.", show_alert=True)
            return

        auth_users = await db.get_authorized_users()
        text = (
            "👑 **مدیریت کاربران و دسترسی‌ها (مخصوص مالک)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"تعداد کاربران مجاز: `{len(auth_users)}` نفر\n\n"
            "هر کاربری که به لیست اضافه شود، یک پنل کاملاً اختصاصی و مجزا خواهد داشت.\n"
            "جهت لغو دسترسی روی ❌ لغو مقابل هر کاربر بزنید یا کاربر جدید اضافه کنید:"
        )
        keyboard = get_users_management_keyboard(auth_users, config.owner_id)
        await safe_edit_message(query, text, reply_markup=keyboard)

    elif data == "add_user":
        if not is_owner:
            await query.answer("دسترسی غیرمجاز", show_alert=True)
            return
        context.user_data["state"] = "WAITING_FOR_USER_ID"
        await safe_edit_message(
            query,
            "➕ لطفاً **آیدی عددی تلگرام** کاربر جدید را ارسال کنید (مثلاً `123456789`):",
            reply_markup=get_back_users_keyboard(),
        )

    elif data.startswith("del_user_"):
        if not is_owner:
            await query.answer("دسترسی غیرمجاز", show_alert=True)
            return
        target_uid = int(data.replace("del_user_", ""))
        await db.remove_authorized_user(target_uid)
        auth_users = await db.get_authorized_users()
        text = f"✅ دسترسی کاربر `{target_uid}` لغو گردید."
        keyboard = get_users_management_keyboard(auth_users, config.owner_id)
        await safe_edit_message(query, text, reply_markup=keyboard)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_user_authorized(user_id):
        return

    state = context.user_data.get("state")
    text = update.effective_message.text.strip()
    settings = await db.get_user_settings(user_id)
    is_owner = (user_id == config.owner_id)
    menu_msg_id = context.user_data.get("menu_msg_id")

    # حذف پیام ارسالی کاربر برای تمیز ماندن محیط چت
    try:
        await update.effective_message.delete()
    except Exception:
        pass

    async def update_previous_or_send(new_text: str, reply_markup):
        if menu_msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=menu_msg_id,
                    text=new_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown",
                )
                return
            except Exception:
                pass
        msg = await context.bot.send_message(
            chat_id=user_id,
            text=new_text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
        context.user_data["menu_msg_id"] = msg.message_id

    # 1. رمز دومرحله‌ای
    if state == "WAITING_FOR_2FA":
        success, msg = await user_client_manager.submit_2fa_password(user_id, text)
        context.user_data["state"] = None
        await update_previous_or_send(msg, get_back_keyboard())

    # 2. افزودن کانال مبدا
    elif state == "WAITING_FOR_SOURCE":
        if text not in settings.sources:
            settings.sources.append(text)
            await db.save_user_settings(user_id, settings)
            context.user_data["state"] = None
            await update_previous_or_send(
                f"✅ کانال `{text}` به لیست منابع شما افزوده شد.",
                get_sources_keyboard(settings.sources),
            )
        else:
            await update_previous_or_send(
                "این کانال از قبل در لیست منابع شما موجود است.",
                get_sources_keyboard(settings.sources),
            )

    # 3. تنظیم کانال مقصد
    elif state == "WAITING_FOR_DEST":
        settings.dest_channel = text
        await db.save_user_settings(user_id, settings)
        context.user_data["state"] = None
        await update_previous_or_send(
            f"✅ کانال مقصد شما با موفقیت ثبت شد:\n`{text}`",
            get_back_keyboard(),
        )

    # 4. تنظیم امضا
    elif state == "WAITING_FOR_SIG":
        settings.signature = "" if text.lower() == "none" else text
        await db.save_user_settings(user_id, settings)
        context.user_data["state"] = None
        sig_disp = settings.signature if settings.signature else "بدون امضا"
        await update_previous_or_send(
            f"✅ امضای فوتر شما ذخیره شد:\n`{sig_disp}`",
            get_back_keyboard(),
        )

    # 5. تنظیم فاصله زمانی اسکن
    elif state == "WAITING_FOR_INTERVAL":
        if text.isdigit() and int(text) >= 1:
            settings.interval_min = int(text)
            await db.save_user_settings(user_id, settings)
            context.user_data["state"] = None
            await update_previous_or_send(
                f"✅ فاصله زمانی اسکن به `{settings.interval_min}` دقیقه تنظیم گردید.",
                get_back_keyboard(),
            )
        else:
            await update_previous_or_send(
                "⚠️ لطفاً یک عدد صحیح معتبر بزرگتر از صفر وارد کنید.",
                get_back_keyboard(),
            )

    # 6. افزودن کاربر جدید توسط مالک
    elif state == "WAITING_FOR_USER_ID" and is_owner:
        if text.isdigit():
            new_uid = int(text)
            await db.add_authorized_user(new_uid)
            context.user_data["state"] = None
            auth_users = await db.get_authorized_users()
            await update_previous_or_send(
                f"✅ کاربر `{new_uid}` با موفقیت به لیست مجاز افزوده شد و اکنون پنل اختصاصی خود را دارد.",
                get_users_management_keyboard(auth_users, config.owner_id),
            )
        else:
            await update_previous_or_send(
                "⚠️ لطفاً یک آیدی عددی تلگرام معتبر (فقط ارقام) ارسال کنید.",
                get_back_users_keyboard(),
            )

    # حالت پیش‌فرض: بازگشت به داشبورد
    else:
        text_dash = await render_dashboard_text(user_id)
        keyboard = get_main_menu_keyboard(settings.running, settings.send_photo, settings.send_video, is_owner=is_owner)
        await update_previous_or_send(text_dash, keyboard)
