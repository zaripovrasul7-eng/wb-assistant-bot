"""
Главный файл WB-бота WB_Assistant7_bot.

Переменные окружения (задаются на Railway):
  WB_STATS_TOKEN     — токен статистики WB (только чтение)
  WB_ADV_TOKEN       — токен рекламы WB (только чтение)
  TELEGRAM_BOT_TOKEN — токен бота от BotFather
  OWNER_CHAT_ID      — ваш личный Telegram chat ID
  WB_WORK_CHAT_ID    — ID группы "WB рабочий чат" (вы + Юля)
  WB_GENERAL_CHAT_ID — ID группы "WB общий чат" (вы + Юля + Элина)
  REPORT_HOUR        — час отправки по МСК (по умолчанию 7)
"""

import os, logging, asyncio, pytz
from datetime import datetime

from telegram import Bot
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from wb_api   import WBClient
from analyzer import (
    analyze_orders, analyze_stocks, analyze_adv,
    analyze_ratings, analyze_profit, calc_buyout_rate
)
from formatter import (
    format_owner_report,
    format_work_chat_report,
    format_general_chat_report,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("wb_bot")

# ── Конфигурация ──
WB_STATS_TOKEN     = os.environ["WB_STATS_TOKEN"]
WB_ADV_TOKEN       = os.environ["WB_ADV_TOKEN"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OWNER_CHAT_ID      = int(os.environ["OWNER_CHAT_ID"])
WB_WORK_CHAT_ID    = int(os.environ["WB_WORK_CHAT_ID"])    if os.environ.get("WB_WORK_CHAT_ID")    else None
WB_GENERAL_CHAT_ID = int(os.environ["WB_GENERAL_CHAT_ID"]) if os.environ.get("WB_GENERAL_CHAT_ID") else None
REPORT_HOUR        = int(os.environ.get("REPORT_HOUR", "7"))
MOSCOW_TZ          = pytz.timezone("Europe/Moscow")


async def send_daily_report():
    logger.info("📡 Сбор данных из WB API...")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    wb  = WBClient(stats_token=WB_STATS_TOKEN, adv_token=WB_ADV_TOKEN)

    orders       = wb.get_orders(days_back=7)
    sales        = wb.get_sales(days_back=14)
    stocks       = wb.get_stocks()
    campaign_ids = wb.get_campaign_ids()
    adv_stats    = wb.get_adv_stats(campaign_ids) if campaign_ids else []
    nm_report    = wb.get_nm_report(days_back=7)
    weekly       = wb.get_weekly_report()

    metrics, order_alerts        = analyze_orders(orders)
    metrics.buyout_rate          = calc_buyout_rate(orders, sales)
    stock_alerts                 = analyze_stocks(stocks, orders)
    tacoo, campaigns, adv_alerts = analyze_adv(adv_stats)
    rating_alerts                = analyze_ratings(nm_report)
    profit_items                 = analyze_profit(weekly, adv_stats)
    metrics.tacoo                = tacoo

    logger.info(f"Алертов: реклама={len(adv_alerts)}, склад={len(stock_alerts)}, "
                f"заказы={len(order_alerts)}, рейтинг={len(rating_alerts)}, "
                f"товаров с ЧП<15%={sum(1 for p in profit_items if p.needs_attention)}")

    # 1. Вам в личку — финансы + ЧП
    await safe_send(bot, OWNER_CHAT_ID, format_owner_report(
        metrics, order_alerts, stock_alerts, adv_alerts, profit_items, tacoo
    ))

    # 2. "WB рабочий чат" — для вас и Юли (реклама, склад, рейтинг, рекомендации)
    if WB_WORK_CHAT_ID:
        await safe_send(bot, WB_WORK_CHAT_ID, format_work_chat_report(
            metrics, order_alerts, stock_alerts, adv_alerts,
            campaigns, rating_alerts, tacoo
        ))

    # 3. "WB общий чат" — только рейтинг для Элины
    if WB_GENERAL_CHAT_ID:
        await safe_send(bot, WB_GENERAL_CHAT_ID, format_general_chat_report(rating_alerts))

    logger.info(f"✅ Готово. Следующий отчёт в {REPORT_HOUR}:00 МСК")


async def safe_send(bot: Bot, chat_id: int, text: str):
    try:
        for chunk in _split(text, 4000):
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
    except TelegramError as e:
        logger.error(f"Ошибка отправки в {chat_id}: {e}")


def _split(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, current, length = [], [], 0
    for line in text.split("\n"):
        if length + len(line) + 1 > limit:
            chunks.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


async def handle_updates(bot: Bot):
    offset = None
    while True:
        try:
            updates = await bot.get_updates(offset=offset, timeout=20)
            for upd in updates:
                offset = upd.update_id + 1
                msg = upd.message
                if not msg:
                    continue
                chat_id = msg.chat.id
                text    = (msg.text or "").strip()

                if text == "/start":
                    await bot.send_message(chat_id, parse_mode="Markdown", text=(
                        f"👋 *WB\\_Assistant7\\_bot запущен!*\n\n"
                        f"Ежедневный отчёт в *{REPORT_HOUR}:00 МСК*.\n\n"
                        f"/report — отчёт прямо сейчас\n"
                        f"/status — проверить работу бота\n"
                        f"/chatid — узнать ID этого чата"
                    ))

                elif text == "/report":
                    await bot.send_message(chat_id, "⏳ Собираю данные из WB, подождите...")
                    await send_daily_report()

                elif text == "/status":
                    now = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")
                    await bot.send_message(chat_id, parse_mode="Markdown", text=(
                        f"✅ *Бот работает*\n"
                        f"Время МСК: `{now}`\n"
                        f"Отчёт в {REPORT_HOUR}:00 МСК"
                    ))

                elif text == "/chatid":
                    # Специальная команда чтобы узнать ID группы
                    ctype = msg.chat.type
                    cname = msg.chat.title or msg.chat.first_name or "—"
                    await bot.send_message(chat_id, parse_mode="Markdown", text=(
                        f"📍 *Информация о чате:*\n"
                        f"ID: `{chat_id}`\n"
                        f"Название: {cname}\n"
                        f"Тип: {ctype}\n\n"
                        f"Скопируйте ID и вставьте в Railway как переменную"
                    ))

        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await asyncio.sleep(5)


async def main():
    logger.info("🚀 WB_Assistant7_bot запускается...")

    scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
    scheduler.add_job(send_daily_report, "cron", hour=REPORT_HOUR, minute=0)
    scheduler.start()

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(OWNER_CHAT_ID, parse_mode="Markdown", text=(
            f"✅ *WB\\_Assistant7\\_bot запущен!*\n"
            f"Отчёт ежедневно в *{REPORT_HOUR}:00 МСК*\n\n"
            f"Напишите /chatid в каждой группе чтобы узнать ID группы"
        ))
    except Exception as e:
        logger.error(f"Стартовое сообщение: {e}")

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await handle_updates(bot)


if __name__ == "__main__":
    asyncio.run(main())
