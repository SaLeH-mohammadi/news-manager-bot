from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_menu_keyboard(
    running: bool, send_photo: bool, send_video: bool, is_owner: bool = False
) -> InlineKeyboardMarkup:
    status_btn = "وضعیت ربات: روشن (فعال)" if running else "وضعیت ربات: خاموش (متوقف)"
    status_style = "success" if running else "danger"

    photo_btn = "عکس: فعال ✅" if send_photo else "عکس: غیرفعال ❌"
    photo_style = "success" if send_photo else "danger"

    video_btn = "ویدیو: فعال ✅" if send_video else "ویدیو: غیرفعال ❌"
    video_style = "success" if send_video else "danger"

    keyboard = [
        # Toggle bot running
        [InlineKeyboardButton(status_btn, callback_data="toggle_running", style=status_style)],
        # Primary actions
        [
            InlineKeyboardButton("🔄 اسکن دستی", callback_data="scan_now", style="primary"),
            InlineKeyboardButton("🚀 انتشار فوری", callback_data="publish_now", style="success"),
        ],
        # MTProto Userbot
        [InlineKeyboardButton("📱 ورود / اتصال اکانت (QR)", callback_data="qr_login", style="primary")],
        # Sources
        [InlineKeyboardButton("📋 مدیریت کانال‌های مبدا", callback_data="menu_sources", style="primary")],
        # Destination & Signature
        [
            InlineKeyboardButton("📢 کانال مقصد", callback_data="menu_dest", style="primary"),
            InlineKeyboardButton("✍️ امضای خبر", callback_data="menu_sig", style="primary"),
        ],
        # Interval
        [InlineKeyboardButton("⏱ تنظیم فاصله اسکن", callback_data="menu_interval", style="primary")],
        # Media Toggles
        [
            InlineKeyboardButton(photo_btn, callback_data="toggle_photo", style=photo_style),
            InlineKeyboardButton(video_btn, callback_data="toggle_video", style=video_style),
        ],
        # Stats & Help
        [
            InlineKeyboardButton("📊 وضعیت و آمار صف", callback_data="menu_stats", style="primary"),
            InlineKeyboardButton("❓ راهنمای کاربری", callback_data="menu_help", style="primary"),
        ],
    ]

    # Owner-Only Button: User Access Management
    if is_owner:
        keyboard.append(
            [InlineKeyboardButton("👑 مدیریت دسترسی کاربران", callback_data="menu_users", style="primary")]
        )

    return InlineKeyboardMarkup(keyboard)


def get_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 پاک‌سازی تاریخچه خبرهای تکراری", callback_data="clear_hashes", style="danger")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu", style="danger")],
    ])


def get_users_management_keyboard(authorized_users: List[int], owner_id: int) -> InlineKeyboardMarkup:
    keyboard = []
    other_users = [u for u in authorized_users if u != owner_id]

    for uid in other_users:
        keyboard.append(
            [
                InlineKeyboardButton(f"👤 کاربر: {uid}", callback_data=f"noop_{uid}", style="primary"),
                InlineKeyboardButton("❌ لغو دسترسی", callback_data=f"del_user_{uid}", style="danger"),
            ]
        )

    keyboard.append([InlineKeyboardButton("➕ افزودن کاربر جدید", callback_data="add_user", style="success")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu", style="danger")])
    return InlineKeyboardMarkup(keyboard)


def get_sources_keyboard(sources: List[str]) -> InlineKeyboardMarkup:
    keyboard = []
    for idx, src in enumerate(sources):
        keyboard.append(
            [
                InlineKeyboardButton(f"📡 {src}", callback_data=f"noop_{idx}", style="primary"),
                InlineKeyboardButton("❌ حذف", callback_data=f"del_src_{idx}", style="danger"),
            ]
        )
    keyboard.append([InlineKeyboardButton("➕ افزودن کانال مبدا جدید", callback_data="add_source", style="success")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu", style="danger")])
    return InlineKeyboardMarkup(keyboard)


def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu", style="danger")]]
    )


def get_back_users_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 بازگشت به مدیریت کاربران", callback_data="menu_users", style="danger")]]
    )
