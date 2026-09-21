import logging
from typing import Optional
from openai import AsyncOpenAI
from config import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """شما یک سردبیر ارشد خبری و روزنامه‌نگار حرفه‌ای در یک خبرگزاری معتبر فارسی هستید.
وظیفه شما بازنویسی، ترجمه و ویرایش حرفه‌ای اخبار خام دریافتی از کانال‌های مختلف است.

قوانین الزامی:
۱. پالایش محتوا: تمامی تبلیغات، لینک‌های اینترنتی، آیدی کانال‌ها (@id)، دعوت به عضویت، لینک‌های اسپانسری، پیام‌های شرط‌بندی و واترمارک‌های منبع را به‌طور کامل حذف کنید.
۲. ترجمه و بازنویسی: در صورتی که خبر به زبانی غیر از فارسی (انگلیسی، عربی و غیره) باشد، آن را با حفظ کامل امانت‌داری، شفاف و روان به زبان فارسی معیار ترجمه کنید.
۳. ساختار استاندارد پست:
   - تیتر: با یک ایموجی خبری مناسب (مانند 🔴، ⚡، 🚨، 📌، 🌍) و یک تیتر جذاب، دقیق و موجز شروع شود.
   - بدنه خبر: در ۲ الی ۴ بند کوتاه، اصل خبر (چه اتفاقی افتاده، جزئیات مهم و پیامدها) بدون حاشیه‌پردازی بیان شود.
   - نگارش: رعایت دقیق نیم‌فاصله‌ها و قواعد ویرایشی زبان فارسی.
۴. فیلتر تبلیغات و محتوای نامربوط: اگر پیام دریافتی صرفاً یک تبلیغ، پیام تبریک/تسلیت بی‌محتوا، شایعه زرد، یا بدون ارزش خبری است، فقط و فقط کلمه «REJECT» را برگردانید.
۵. قالب پاسخ: فقط متن نهایی خبر را بدون هیچ‌گونه سلام، توضیح اضافه، تگ‌های مارک‌داون کد (```) یا پیش‌گفتار بازگردانید.
"""


class AIService:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=config.ninerouter_base_url,
            api_key=config.ninerouter_api_key,
        )
        self.model = config.ninerouter_model

    async def rewrite_news(self, raw_text: str) -> Optional[str]:
        if not raw_text or len(raw_text.strip()) < 15:
            return None

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"لطفاً متن خام زیر را به یک پست خبری استاندارد و رسمی تبدیل کن:\n\n{raw_text}",
                    },
                ],
                temperature=0.3,
                max_tokens=1000,
            )

            result = response.choices[0].message.content
            if not result:
                return None

            cleaned_result = result.strip()
            if cleaned_result.upper() == "REJECT" or "REJECT" in cleaned_result:
                logger.info("AI classified the message as non-news/ad (REJECT).")
                return None

            return cleaned_result
        except Exception as e:
            logger.error(f"Error calling 9router AI API: {e}")
            return None


ai_service = AIService()
