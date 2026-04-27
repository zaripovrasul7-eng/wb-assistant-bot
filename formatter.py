"""
Форматирование сообщений — стиль Sirena AI: чистый, по артикулам.
"""

from datetime import datetime, timedelta, date
from collections import defaultdict
from analyzer import (
    DailyMetrics, SKUAlert, AdvCampaignInfo, RatingAlert, ProfitItem,
    drr_emoji, drr_label, rating_emoji, rating_label,
    DRR_GREEN, MIN_PROFIT_PCT
)
import pytz

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

MIN_STOCK_FILTER = 5      # товары с остатком < 5 шт не показываем
MIN_SALES_FILTER = 0.1    # и средними продажами < 0.1/день — это мёртвый сток


def _short_name(name: str, nm: int, max_len: int = 28) -> str:
    """Название + артикул, обрезанное до max_len символов."""
    short = name[:max_len] + ("…" if len(name) > max_len else "")
    return f"{short} (#{nm})"


def _today_range() -> str:
    """Показываем вчерашний полный день — как у Sirena AI."""
    now = datetime.now(MOSCOW_TZ)
    day2ago   = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return f"{day2ago} — {yesterday}"


# ════════════════════════════════════════════════════════
#  ВАМ В ЛИЧКУ
# ════════════════════════════════════════════════════════

def format_owner_report(
    metrics: DailyMetrics,
    order_alerts: list[SKUAlert],
    stock_alerts: list[SKUAlert],
    adv_alerts: list[SKUAlert],
    profit_items: list[ProfitItem],
) -> str:
    now  = datetime.now(MOSCOW_TZ)
    tacoo = metrics.tacoo
    drr   = metrics.drr
    tacoo_icon = drr_emoji(max(tacoo, drr))
    tacoo_str  = f"{tacoo:.1f}%" if tacoo > 0 else "нет данных"
    drr_str    = f"{drr:.1f}%"   if drr   > 0 else "нет данных"

    total_revenue = sum(p.revenue    for p in profit_items)
    total_net     = sum(p.net_profit for p in profit_items)
    avg_net_pct   = (total_net / total_revenue * 100) if total_revenue > 0 else 0.0
    low_profit    = [p for p in profit_items if p.needs_attention]

    lines = [
        f"📊 *Личный отчёт*",
        f"📅 {_today_range()}",
        "",
        f"💰 Продажи:  *{metrics.revenue_today:,.0f} ₽*",
        f"📦 Заказов:  *{metrics.orders_today} шт*",
        f"{tacoo_icon} TACOO: *{tacoo_str}* | ДРР: *{drr_str}*",
        f"🔄 Выкуп:    *{metrics.buyout_rate:.0f}%*",
    ]

    if profit_items:
        cp_icon = "✅" if avg_net_pct >= 15 else ("🟡" if avg_net_pct >= 10 else "🔴")
        lines += [
            "",
            f"💎 *Чистая прибыль (неделя):*",
            f"   Выручка: {total_revenue:,.0f} ₽",
            f"   ЧП: {total_net:,.0f} ₽ ({avg_net_pct:.1f}%)",
            f"   УСН 7%: {sum(p.tax for p in profit_items):,.0f} ₽",
            f"   {cp_icon} Средняя маржа: *{avg_net_pct:.1f}%*",
        ]

    # Критичные алерты
    critical = [a for a in (adv_alerts + stock_alerts + order_alerts) if a.severity == "critical"]
    if critical:
        lines += ["", "🚨 *Срочно:*"]
        for a in critical:
            icon = {"drr":"📉","stock":"📦","orders":"📊"}.get(a.alert_type,"⚠")
            lines.append(f"{icon} {_short_name(a.name, a.nmId)} — {a.message}")

    # ЧП ниже 15%
    if low_profit:
        lines += ["", f"⚠ *ЧП < {MIN_PROFIT_PCT:.0f}% — требуют внимания:*"]
        for p in low_profit[:7]:
            icon = "🔴" if p.net_profit_pct < 10 else "🟡"
            lines.append(f"{icon} {_short_name(p.name, p.nmId)} — ЧП {p.net_profit_pct:.1f}%")
            lines.append(f"   👉 {p.recommendation}")

    if not critical and not low_profit:
        lines += ["", "✅ Всё в норме. Хорошего дня!"]

    return "\n".join(lines)


# ════════════════════════════════════════════════════════
#  "WB РАБОЧИЙ ЧАТ" — вы + Юля
# ════════════════════════════════════════════════════════

def format_work_chat_report(
    metrics: DailyMetrics,
    order_alerts: list[SKUAlert],
    stock_alerts: list[SKUAlert],
    adv_alerts: list[SKUAlert],
    campaigns: list[AdvCampaignInfo],
    rating_alerts: list[RatingAlert],
) -> str:
    now  = datetime.now(MOSCOW_TZ)
    tacoo = metrics.tacoo
    drr   = metrics.drr
    tacoo_icon = drr_emoji(max(tacoo, drr))
    tacoo_str  = f"{tacoo:.1f}%" if tacoo > 0 else "нет данных"
    drr_str    = f"{drr:.1f}%"   if drr   > 0 else "нет данных"

    orders_delta = ""
    if metrics.orders_yesterday > 0:
        diff = metrics.orders_today - metrics.orders_yesterday
        sign = "+" if diff >= 0 else ""
        orders_delta = f" ({sign}{diff} vs вчера)"

    lines = [
        f"📋 *WB Рабочий чат*",
        f"📅 {_today_range()}",
        "───────────────────",
        f"📦 Заказов:  *{metrics.orders_today} шт*{orders_delta}",
        f"💰 Выручка:  *{metrics.revenue_today:,.0f} ₽*",
        f"{tacoo_icon} TACOO:    *{tacoo_str}*",
        f"📈 ДРР:      *{drr_str}*",
        f"🔄 Выкуп:    *{metrics.buyout_rate:.0f}%*",
        "───────────────────",
    ]

    # ── Реклама по кампаниям ──
    active_camps = [c for c in campaigns if c.drr > 0 or c.orders > 0]
    if active_camps:
        lines.append("📣 *Рекламные кампании:*")
        for c in active_camps[:20]:
            icon = drr_emoji(c.drr)
            lines.append(
                f"{icon} {c.name[:30]} — ДРР *{c.drr:.1f}%* | {c.spend_per_day:.0f} ₽/д"
            )
            if c.drr > DRR_GREEN:
                lines.append(f"   👉 {c.recommendation}")
        lines.append("")

    # ── Склад — только реальные товары (остаток ≥ 5 шт) ──
    real_stock = [a for a in stock_alerts if _is_real_stock(a)]
    if real_stock:
        lines.append("📦 *Остатки — требуют внимания:*")
        seen = set()
        for a in real_stock:
            key = (a.nmId, a.alert_type)
            if key in seen:
                continue
            seen.add(key)
            icon = "🔴" if a.severity == "critical" else "🟡"
            lines.append(f"{icon} {_short_name(a.name, a.nmId)}")
            lines.append(f"   {a.message} — {a.action}")
        lines.append("")

    # ── Падение заказов — только значимые ──
    real_orders = [a for a in order_alerts if _is_significant_drop(a)]
    if real_orders:
        lines.append("📊 *Падение заказов по артикулам:*")
        seen = set()
        for a in real_orders:
            if a.nmId in seen:
                continue
            seen.add(a.nmId)
            lines.append(f"📉 {_short_name(a.name, a.nmId)} — {a.message}")
            lines.append(f"   👉 {a.action}")
        lines.append("")

    # ── Рейтинг ──
    if rating_alerts:
        lines.append("⭐ *Рейтинг (проблемные товары):*")
        for a in rating_alerts:
            lines.append(
                f"{rating_emoji(a.rating_now)} {_short_name(a.name, a.nmId)} — {a.message}"
            )
        lines.append("")

    if not active_camps and not real_stock and not real_orders and not rating_alerts:
        lines.append("✅ Показатели в норме!")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════
#  "WB ОБЩИЙ ЧАТ" — рейтинг для Элины
# ════════════════════════════════════════════════════════

def format_general_chat_report(rating_alerts: list[RatingAlert]) -> str:
    now  = datetime.now(MOSCOW_TZ)
    lines = [
        f"⭐ *Рейтинг товаров*",
        f"📅 {now.strftime('%d %b %Y')}",
        "",
    ]

    critical = [a for a in rating_alerts if a.severity == "critical"]
    warnings = [a for a in rating_alerts if a.severity == "warning"]

    if critical:
        lines.append("🔴 *Элина, срочно — рейтинг ниже 4.5:*")
        for a in critical:
            lines.append(f"• *{_short_name(a.name, a.nmId)}*")
            lines.append(f"  {a.message}")
            lines.append(f"  👉 Срочный анализ отзывов, работа с покупателями")
        lines.append("")

    if warnings:
        lines.append("🟡 *Рейтинг снижается — нужен анализ:*")
        for a in warnings:
            lines.append(f"• {_short_name(a.name, a.nmId)} — {a.message}")
        lines.append("")
        lines.append("👉 Элина, разбери последние отзывы по этим товарам")

    if not critical and not warnings:
        lines.append(
            "✅ Рейтинг всех товаров в норме!\n\n"
            "_<4.5 🔴 критично | 4.6 🟡 допустимо | 4.7 🟢 хорошо | ≥4.8 ✅ отлично_"
        )

    return "\n".join(lines)


# ════════════════════════════════════════════════════════
#  Фильтры
# ════════════════════════════════════════════════════════

def _is_real_stock(alert: SKUAlert) -> bool:
    """Пропускаем товары с нулевым остатком — скорее всего не продаём."""
    msg = alert.message.lower()
    # Извлекаем количество штук из сообщения вида "Остаток на X дней (Y шт.)"
    try:
        qty_str = msg.split("(")[1].split(" шт")[0]
        qty = int(qty_str)
        return qty >= MIN_STOCK_FILTER
    except Exception:
        return True  # если не можем разобрать — показываем


def _is_significant_drop(alert: SKUAlert) -> bool:
    """Пропускаем падения где абсолютные цифры ничтожны (1→0 шт.)."""
    msg = alert.message
    try:
        # Формат: "Заказы −X% за 2 дня (A→B шт.)"
        counts = msg.split("(")[1].split(" шт")[0]
        before = int(counts.split("→")[0])
        return before >= 3   # игнорируем если базовое значение < 3 заказов
    except Exception:
        return True
