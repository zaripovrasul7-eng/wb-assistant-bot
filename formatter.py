"""
Форматирование сообщений для Telegram.

Получатели:
  OWNER (личка)      — выручка, TACOO, склад, реклама, ЧИСТАЯ ПРИБЫЛЬ + рекомендации по ЧП
  WB_WORK_CHAT       — "WB рабочий чат" (вы + Юля): всё + ДРР по кампаниям + рекомендации по РК
  WB_GENERAL_CHAT    — "WB общий чат" (вы + Юля + Элина): только рейтинг для Элины
"""

from datetime import datetime
from analyzer import (
    DailyMetrics, SKUAlert, AdvCampaignInfo, RatingAlert, ProfitItem,
    drr_emoji, drr_label, rating_emoji, rating_label,
    DRR_GREEN, MIN_PROFIT_PCT
)
import pytz

MOSCOW_TZ = pytz.timezone("Europe/Moscow")


# ════════════════════════════════════════════════════════
#  ВАМ В ЛИЧКУ — полный отчёт с чистой прибылью
# ════════════════════════════════════════════════════════

def format_owner_report(
    metrics: DailyMetrics,
    order_alerts: list[SKUAlert],
    stock_alerts: list[SKUAlert],
    adv_alerts: list[SKUAlert],
    profit_items: list[ProfitItem],
    tacoo: float,
) -> str:
    now  = datetime.now(MOSCOW_TZ)
    date = now.strftime("%d %b %Y")
    tacoo_icon = drr_emoji(tacoo)
    tacoo_warn = " ⚠ ВЫШЕ ЦЕЛИ" if tacoo > DRR_GREEN else ""

    orders_delta = ""
    if metrics.orders_yesterday > 0:
        diff = metrics.orders_today - metrics.orders_yesterday
        sign = "+" if diff >= 0 else ""
        orders_delta = f" ({sign}{diff} vs вчера)"

    # Считаем суммарную ЧП
    total_revenue   = sum(p.revenue    for p in profit_items)
    total_net       = sum(p.net_profit for p in profit_items)
    avg_net_pct     = (total_net / total_revenue * 100) if total_revenue > 0 else 0.0
    low_profit_items= [p for p in profit_items if p.needs_attention]

    lines = [
        f"📊 *Личный отчёт — {date}*",
        "",
        f"💰 Выручка (сегодня): *{metrics.revenue_today:,.0f} ₽*",
        f"📦 Заказов: *{metrics.orders_today}*{orders_delta}",
        f"{tacoo_icon} TACOO: *{tacoo:.1f}%*{tacoo_warn}",
        f"🔄 Выкуп: *{metrics.buyout_rate:.0f}%*",
        "",
    ]

    # ── Чистая прибыль ──
    if profit_items:
        cp_icon = "✅" if avg_net_pct >= 15 else ("🟡" if avg_net_pct >= 10 else "🔴")
        lines += [
            "💎 *Чистая прибыль (неделя):*",
            f"   Выручка:  {total_revenue:,.0f} ₽",
            f"   ЧП:       {total_net:,.0f} ₽  ({avg_net_pct:.1f}%)",
            f"   УСН 7%:   {sum(p.tax for p in profit_items):,.0f} ₽",
            f"   {cp_icon} Средняя маржа: *{avg_net_pct:.1f}%*",
            "",
        ]

        if low_profit_items:
            lines.append(f"⚠ *Товары с ЧП ниже {MIN_PROFIT_PCT:.0f}% — требуют внимания:*")
            for p in low_profit_items[:7]:
                pct_icon = "🔴" if p.net_profit_pct < 10 else "🟡"
                lines.append(f"{pct_icon} *{p.name[:30]}*  ЧП: {p.net_profit_pct:.1f}%")
                lines.append(f"   👉 {p.recommendation}")
            lines.append("")

    # ── Критичные алерты ──
    all_critical = [a for a in (adv_alerts + stock_alerts + order_alerts) if a.severity == "critical"]
    if all_critical:
        lines.append("🚨 *СРОЧНО:*")
        for a in all_critical:
            icon = {"drr": "📉", "stock": "📦", "orders": "📊"}.get(a.alert_type, "⚠")
            lines.append(f"{icon} *{a.name}* — {a.message}")
            lines.append(f"   👉 {a.action}")
        lines.append("")

    # ── Предупреждения ──
    all_warn = [a for a in (adv_alerts + stock_alerts + order_alerts) if a.severity == "warning"]
    if all_warn:
        lines.append("🟡 *Следить:*")
        for a in all_warn:
            icon = {"drr": "📉", "stock": "📦", "orders": "📊"}.get(a.alert_type, "⚠")
            lines.append(f"{icon} {a.name} — {a.message}")
        lines.append("")

    total_alerts = len(all_critical) + len(all_warn)
    if total_alerts == 0 and not low_profit_items:
        lines.append("✅ Всё в норме. Хорошего дня!")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════
#  "WB РАБОЧИЙ ЧАТ" — для вас и Юли
# ════════════════════════════════════════════════════════

def format_work_chat_report(
    metrics: DailyMetrics,
    order_alerts: list[SKUAlert],
    stock_alerts: list[SKUAlert],
    adv_alerts: list[SKUAlert],
    campaigns: list[AdvCampaignInfo],
    rating_alerts: list[RatingAlert],
    tacoo: float,
) -> str:
    now  = datetime.now(MOSCOW_TZ)
    date = now.strftime("%d %b %Y")
    tacoo_icon = drr_emoji(tacoo)
    tacoo_warn = " ⚠ ВЫШЕ ЦЕЛИ" if tacoo > DRR_GREEN else ""

    orders_delta = ""
    if metrics.orders_yesterday > 0:
        diff = metrics.orders_today - metrics.orders_yesterday
        sign = "+" if diff >= 0 else ""
        orders_delta = f" ({sign}{diff})"

    lines = [
        f"📋 *WB Рабочий чат — {date}*",
        "",
        f"📦 Заказов: *{metrics.orders_today}*{orders_delta}",
        f"💰 Выручка: *{metrics.revenue_today:,.0f} ₽*",
        f"{tacoo_icon} TACOO: *{tacoo:.1f}%*{tacoo_warn}",
        f"🔄 Выкуп: *{metrics.buyout_rate:.0f}%*",
        "",
    ]

    # ── Срочные задачи для Юли ──
    all_critical = [a for a in (adv_alerts + stock_alerts + order_alerts) if a.severity == "critical"]
    if all_critical:
        lines.append("🚨 *Юля, срочно:*")
        for a in all_critical:
            icon = {"drr": "📉", "stock": "📦", "orders": "📊"}.get(a.alert_type, "⚠")
            lines.append(f"{icon} *{a.name}* — {a.message}")
            lines.append(f"   👉 {a.action}")
        lines.append("")

    # ── ДРР по всем кампаниям ──
    if campaigns:
        lines.append("📣 *Рекламные кампании — ДРР:*")
        for c in campaigns[:15]:
            icon = drr_emoji(c.drr)
            lines.append(f"{icon} {c.name[:32]} — *{c.drr:.1f}%* | {c.spend_per_day:.0f} ₽/д")
            if c.drr > DRR_GREEN:
                lines.append(f"   👉 {c.recommendation}")
        lines.append("")

    # ── Склад ──
    stock_alerts_sorted = sorted(stock_alerts, key=lambda a: 0 if a.severity == "critical" else 1)
    if stock_alerts_sorted:
        lines.append("📦 *Остатки:*")
        for a in stock_alerts_sorted:
            icon = "🔴" if a.severity == "critical" else "🟡"
            lines.append(f"{icon} {a.name} — {a.message}")
            lines.append(f"   👉 {a.action}")
        lines.append("")

    # ── Рейтинг ──
    if rating_alerts:
        lines.append("⭐ *Рейтинг (проблемные товары):*")
        for a in rating_alerts:
            lines.append(f"{rating_emoji(a.rating_now)} {a.name} — {a.message}")
        lines.append("")

    # ── Рекомендации по заказам ──
    if order_alerts:
        lines.append("📊 *Падение заказов:*")
        for a in order_alerts:
            lines.append(f"📉 {a.name} — {a.message}")
            lines.append(f"   👉 {a.action}")
        lines.append("")

    if not all_critical and not [a for a in (adv_alerts + stock_alerts + order_alerts) if a.severity == "warning"]:
        lines.append("✅ Показатели в норме!")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════
#  "WB ОБЩИЙ ЧАТ" — рейтинг для Элины
# ════════════════════════════════════════════════════════

def format_general_chat_report(rating_alerts: list[RatingAlert]) -> str:
    """
    Отчёт в "WB общий чат" — только рейтинг товаров для Элины.
    Элина видит проблемный товар и самостоятельно проводит анализ.
    """
    now  = datetime.now(MOSCOW_TZ)
    date = now.strftime("%d %b")

    lines = [f"⭐ *Рейтинг товаров — {date}*", ""]

    critical = [a for a in rating_alerts if a.severity == "critical"]
    warnings = [a for a in rating_alerts if a.severity == "warning"]

    if critical:
        lines.append("🔴 *Элина, срочно — рейтинг ниже 4.5:*")
        for a in critical:
            lines.append(f"• *{a.name}* — {a.message}")
            lines.append(f"  👉 Срочный анализ отзывов, работа с недовольными покупателями")
        lines.append("")

    if warnings:
        lines.append("🟡 *Нужен анализ — рейтинг снижается:*")
        for a in warnings:
            lines.append(f"• *{a.name}* — {a.message}")
        lines.append("")
        lines.append("👉 Элина, зайди в карточки этих товаров и разбери последние отзывы")

    if not critical and not warnings:
        lines.append("✅ Рейтинг всех товаров в норме!\n\n"
                     "_Пороги: <4.5 🔴 критично | 4.6 🟡 допустимо | 4.7 🟢 хорошо | ≥4.8 ✅ отлично_")

    return "\n".join(lines)
