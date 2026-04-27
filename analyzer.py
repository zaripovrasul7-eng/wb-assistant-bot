"""
Бизнес-логика анализа данных WB.

Пороги ДРР/TACOO:
  ≤6%   🟢 норма
  7–9%  🟡 следить
  10–12% 🔴 проблема
  >12%  🚨 критично

Пороги склада:
  21 день — предупреждение | 15 дней — срочно

Пороги рейтинга:
  ≥4.8 ✅ | 4.7 🟢 | 4.6 🟡 | <4.5 🔴

Падение заказов: 2 дня подряд, база ≥ 3 заказов, падение ≥ 20%
Фильтр мёртвого стока: остаток < 5 шт. И продажи < 0.1/день
"""

import json, os
from collections import defaultdict
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field

# ── Пороги ──────────────────────────────────────────────
DRR_GREEN    = 6.0
DRR_ORANGE   = 9.0
DRR_RED      = 12.0

STOCK_WARN_DAYS   = 21
STOCK_URGENT_DAYS = 15

ORDER_DROP_DAYS = 2
ORDER_DROP_PCT  = 20
ORDER_MIN_BASE  = 3     # минимум заказов в базовый день чтобы считать падение значимым

STOCK_MIN_QTY   = 5     # товары с остатком < 5 шт не показываем (мёртвый сток)
STOCK_MIN_SALES = 0.1   # и продажами < 0.1/день

RATING_CRITICAL   = 4.5
RATING_ACCEPTABLE = 4.6
RATING_GOOD       = 4.7
RATING_EXCELLENT  = 4.8

MIN_PROFIT_PCT = 15.0
TAX_RATE_USN   = 0.07

# ── Эмодзи ──────────────────────────────────────────────
def drr_emoji(v: float) -> str:
    if v <= DRR_GREEN:    return "🟢"
    elif v <= DRR_ORANGE: return "🟡"
    elif v <= DRR_RED:    return "🔴"
    else:                 return "🚨"

def drr_label(v: float) -> str:
    if v <= DRR_GREEN:    return "норма"
    elif v <= DRR_ORANGE: return "следить"
    elif v <= DRR_RED:    return "проблема"
    else:                 return "СТОП — срочная аналитика"

def rating_emoji(r: float) -> str:
    if r >= RATING_EXCELLENT:   return "✅"
    elif r >= RATING_GOOD:      return "🟢"
    elif r >= RATING_ACCEPTABLE:return "🟡"
    else:                       return "🔴"

def rating_label(r: float) -> str:
    if r >= RATING_EXCELLENT:   return "отлично"
    elif r >= RATING_GOOD:      return "хорошо"
    elif r >= RATING_ACCEPTABLE:return "допустимо"
    else:                       return "критично"

# ── Структуры данных ─────────────────────────────────────
@dataclass
class DailyMetrics:
    orders_today:      int   = 0
    orders_yesterday:  int   = 0
    revenue_today:     float = 0.0   # выручка (заказы)
    sales_revenue:     float = 0.0   # выручка (выкупы)
    buyout_rate:       float = 0.0
    buyout_reliable:   bool  = False  # False = данные WB ещё не обновились
    ad_spend:          float = 0.0
    tacoo:             float = 0.0
    drr:               float = 0.0

@dataclass
class SKUAlert:
    nmId:       int
    name:       str
    alert_type: str    # 'drr' | 'stock' | 'orders'
    severity:   str    # 'warning' | 'critical'
    message:    str
    action:     str = ""
    qty:        int = 0   # остаток в штуках (для фильтрации)

@dataclass
class AdvCampaignInfo:
    campaign_id:    int
    name:           str
    drr:            float
    spend_per_day:  float
    orders:         int
    recommendation: str = ""

@dataclass
class RatingAlert:
    nmId:       int
    name:       str
    rating_now: float
    severity:   str
    message:    str

@dataclass
class ProfitItem:
    nmId:           int
    name:           str
    revenue:        float
    cogs:           float
    wb_commission:  float
    logistics:      float
    adv_cost:       float
    storage:        float
    tax:            float
    net_profit:     float
    net_profit_pct: float
    needs_attention:bool
    recommendation: str = ""

# ── Себестоимость ────────────────────────────────────────
def load_costs() -> dict[int, float]:
    path = os.path.join(os.path.dirname(__file__), "costs.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {int(k): float(v) for k, v in data.get("costs", {}).items()}
    except Exception:
        return {}

# ── Имя товара: артикул продавца → категория → номер ────
def _item_name(obj: dict, nm: int) -> str:
    return (obj.get("supplierArticle")
            or obj.get("techSize") and obj.get("subject") and f"{obj['subject']} {obj['techSize']}"
            or obj.get("subject")
            or f"#{nm}")

# ── Анализ заказов ───────────────────────────────────────
def analyze_orders(orders: list) -> tuple[DailyMetrics, list[SKUAlert]]:
    today     = date.today()
    yesterday = today - timedelta(days=1)
    day_2ago  = today - timedelta(days=2)

    by_date: dict[date, dict[int, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"orders": 0, "revenue": 0.0, "name": ""})
    )
    total_today_orders  = 0
    total_today_revenue = 0.0
    total_yest_orders   = 0

    for o in orders:
        try:
            o_date = datetime.fromisoformat(o.get("date", "")[:10]).date()
        except Exception:
            continue
        if o.get("isCancel"):
            continue
        nm  = o.get("nmId", 0)
        # priceWithDisc — цена покупателя со скидкой (самое точное поле)
        rev = float(o.get("priceWithDisc") or
                    o.get("totalPrice", 0) * (1 - float(o.get("discountPercent", 0)) / 100))
        name = _item_name(o, nm)

        by_date[o_date][nm]["orders"]  += 1
        by_date[o_date][nm]["revenue"] += rev
        by_date[o_date][nm]["name"]     = name

        if o_date == today:
            total_today_orders  += 1
            total_today_revenue += rev
        elif o_date == yesterday:
            total_yest_orders   += 1

    # Основная метрика — ВЧЕРАШНИЙ полный день (как у Sirena)
    # "Сегодня" — только частичные данные с 00:00, они всегда занижены
    by_date_total: dict[date, dict] = defaultdict(lambda: {"orders": 0, "revenue": 0.0})
    for o2 in orders:
        try:
            d2 = datetime.fromisoformat(o2.get("date", "")[:10]).date()
        except Exception:
            continue
        if o2.get("isCancel"):
            continue
        r2 = float(o2.get("priceWithDisc") or
                   float(o2.get("totalPrice", 0)) * (1 - float(o2.get("discountPercent", 0)) / 100))
        by_date_total[d2]["orders"]  += 1
        by_date_total[d2]["revenue"] += r2

    metrics = DailyMetrics(
        orders_today     = by_date_total[yesterday]["orders"],    # вчера — полный день
        orders_yesterday = by_date_total[day_2ago]["orders"],     # позавчера — для сравнения
        revenue_today    = by_date_total[yesterday]["revenue"],   # выручка вчера
    )

    # Алерты по падению заказов — только значимые
    alerts = []
    all_nms = set(by_date[yesterday]) | set(by_date[day_2ago])
    for nm in all_nms:
        cnt_y  = by_date[yesterday][nm]["orders"]
        cnt_2  = by_date[day_2ago][nm]["orders"]
        name   = by_date[yesterday][nm]["name"] or by_date[day_2ago][nm]["name"] or f"#{nm}"
        if cnt_2 < ORDER_MIN_BASE:
            continue   # базовое значение слишком мало — не считаем
        drop_pct = (cnt_2 - cnt_y) / cnt_2 * 100
        if drop_pct >= ORDER_DROP_PCT and cnt_y < cnt_2:
            severity = "critical" if drop_pct >= 50 else "warning"
            alerts.append(SKUAlert(
                nmId=nm, name=name, alert_type="orders", severity=severity,
                message=f"Заказы −{drop_pct:.0f}% за 2 дня ({cnt_2}→{cnt_y} шт.)",
                action="Проверьте позиции в поиске и цены конкурентов"
            ))
    return metrics, alerts

# ── Анализ выкупов (продаж) ──────────────────────────────
def calc_sales_revenue_from_nm(nm_report: dict) -> float:
    """Сумма выкупов из nm-report (buyoutsSumRub) — точнее чем sales API."""
    cards = nm_report.get("data", {}).get("cards", [])
    total = 0.0
    for card in cards:
        stats  = card.get("statistics", {})
        period = stats.get("selectedPeriod", {})
        total += float(period.get("buyoutsSumRub", 0) or 0)
    return total


def calc_sales_revenue(sales: list) -> float:
    """Запасной вариант расчёта выкупов через sales API."""
    today = date.today()
    total = 0.0
    for s in sales:
        try:
            s_date = datetime.fromisoformat(s.get("date", "")[:10]).date()
        except Exception:
            continue
        if (today - s_date).days <= 7:
            total += float(s.get("forPay", 0) or s.get("priceWithDisc", 0) or 0)
    return total

def calc_buyout_rate_from_nm(nm_report: dict) -> tuple[float, bool]:
    """
    Правильный расчёт выкупа из nm-report.
    nm-report содержит готовые поля ordersCount и buyoutsCount по каждому артикулу.
    Это тот же источник что используют MPSTATS, Torgstat и другие сервисы.
    Возвращает (процент_выкупа, данные_достоверны).
    """
    cards = nm_report.get("data", {}).get("cards", [])
    total_orders  = 0
    total_buyouts = 0
    for card in cards:
        stats  = card.get("statistics", {})
        period = stats.get("selectedPeriod", {})
        total_orders  += int(period.get("ordersCount",  0) or 0)
        total_buyouts += int(period.get("buyoutsCount", 0) or 0)
    if total_orders == 0:
        return 0.0, False
    rate     = min(total_buyouts / total_orders * 100, 100.0)
    reliable = total_buyouts > 0
    return rate, reliable


def calc_buyout_rate(orders: list, sales: list) -> tuple[float, bool]:
    """
    Выкуп = кол-во продаж / кол-во заказов за последние 30 дней.
    Используем 30 дней чтобы учесть время доставки (до 14 дней).
    forPay > 0 означает подтверждённый выкуп.
    """
    today = date.today()
    cutoff = today - timedelta(days=30)

    ord_cnt  = sum(
        1 for o in orders
        if not o.get("isCancel")
        and _parse_date(o.get("date")) >= cutoff
    )
    # Считаем только реальные выкупы (saleID начинается с S, не с R — возврат)
    sale_cnt = sum(
        1 for s in sales
        if _parse_date(s.get("date")) >= cutoff
        and str(s.get("saleID", "")).startswith("S")
        and float(s.get("forPay", 0) or 0) > 0
    )
    if ord_cnt == 0:
        return 0.0, False
    rate     = min(sale_cnt / ord_cnt * 100, 100.0)
    reliable = sale_cnt >= 5  # минимум 5 выкупов чтобы считать достоверным
    return rate, reliable


def calc_sales_revenue(sales: list) -> float:
    """Выручка по выкупам = сумма forPay за последние 7 дней."""
    today  = date.today()
    cutoff = today - timedelta(days=7)
    return sum(
        float(s.get("forPay", 0) or 0)
        for s in sales
        if _parse_date(s.get("date")) >= cutoff
        and str(s.get("saleID", "")).startswith("S")
        and float(s.get("forPay", 0) or 0) > 0
    )

# ── Анализ остатков ──────────────────────────────────────
def analyze_stocks(stocks: list, orders: list) -> list[SKUAlert]:
    today    = date.today()
    sales_7d = defaultdict(int)
    names    = {}

    for o in orders:
        try:
            o_date = datetime.fromisoformat(o.get("date", "")[:10]).date()
        except Exception:
            continue
        if o.get("isCancel"):
            continue
        if (today - o_date).days <= 7:
            nm = o.get("nmId", 0)
            sales_7d[nm] += 1
            names[nm] = _item_name(o, nm)

    stock_map = defaultdict(int)
    for s in stocks:
        nm = s.get("nmId", 0)
        stock_map[nm] += int(s.get("quantity", 0))
        if nm not in names:
            names[nm] = _item_name(s, nm)

    alerts = []
    for nm, total_qty in stock_map.items():
        avg_sales = sales_7d.get(nm, 0) / 7

        # Фильтр мёртвого стока
        if total_qty == 0:
            continue   # нулевой остаток — всегда пропускаем
        if total_qty < STOCK_MIN_QTY and avg_sales < STOCK_MIN_SALES:
            continue   # меньше 5 шт и почти не продаётся — пропускаем

        if avg_sales < 0.01:
            continue  # товар не продаётся — пропускаем

        days_left = total_qty / avg_sales
        name = names.get(nm, f"#{nm}")

        if days_left <= STOCK_URGENT_DAYS:
            alerts.append(SKUAlert(
                nmId=nm, name=name, alert_type="stock", severity="critical",
                message=f"Остаток на {days_left:.0f} дней ({total_qty} шт.)",
                action="Срочно отправьте поставку!",
                qty=total_qty
            ))
        elif days_left <= STOCK_WARN_DAYS:
            alerts.append(SKUAlert(
                nmId=nm, name=name, alert_type="stock", severity="warning",
                message=f"Остаток на {days_left:.0f} дней ({total_qty} шт.)",
                action="Запланируйте поставку",
                qty=total_qty
            ))

    return sorted(alerts, key=lambda a: (0 if a.severity == "critical" else 1))

# ── Анализ рекламы ───────────────────────────────────────
def analyze_adv(adv_stats: list, orders_revenue: float, sales_revenue: float
                ) -> tuple[float, float, float, list[AdvCampaignInfo], list[SKUAlert]]:
    """
    Возвращает: (tacoo, drr, total_spend, campaigns, alerts)
    TACOO = spend / orders_revenue * 100
    ДРР   = spend / sales_revenue * 100
    """
    campaigns   = []
    total_spend = 0.0

    for camp in adv_stats:
        cid  = camp.get("advertId", 0)
        name = camp.get("advertName", f"Кампания #{cid}")
        spend = rev = orders = days_count = 0
        for d in camp.get("days", []):
            spend      += float(d.get("sum", 0))
            orders     += int(d.get("orders", 0))
            rev        += float(d.get("sum_price", 0))
            days_count += 1

        # ДРР кампании = расходы / выручка от этой кампании
        camp_drr = (spend / rev * 100) if rev > 0 else (999.0 if spend > 0 else 0.0)
        avg_spend = spend / max(days_count, 1)
        rec = _adv_recommendation(camp_drr, orders)

        campaigns.append(AdvCampaignInfo(
            campaign_id=cid, name=name, drr=camp_drr,
            spend_per_day=avg_spend, orders=orders, recommendation=rec
        ))
        total_spend += spend

    # Общий TACOO и ДРР
    tacoo = (total_spend / orders_revenue * 100) if orders_revenue > 0 else 0.0
    drr   = (total_spend / sales_revenue  * 100) if sales_revenue  > 0 else 0.0

    alerts = []
    for c in campaigns:
        if c.drr > DRR_GREEN:
            severity = "critical" if c.drr > DRR_RED else "warning"
            alerts.append(SKUAlert(
                nmId=c.campaign_id, name=c.name, alert_type="drr", severity=severity,
                message=f"ДРР {c.drr:.1f}% ({drr_label(c.drr)}) | {c.spend_per_day:.0f} ₽/день",
                action=c.recommendation
            ))

    campaigns.sort(key=lambda c: c.drr, reverse=True)
    alerts.sort(key=lambda a: 0 if a.severity == "critical" else 1)
    return tacoo, drr, total_spend, campaigns, alerts


def _adv_recommendation(drr: float, orders: int) -> str:
    if drr > DRR_RED:      return "Приостановить кампанию, провести аналитику ключевых запросов"
    elif drr > DRR_ORANGE: return "Снизить ставки на 20–30%, убрать нерабочие ключи"
    elif drr > DRR_GREEN:  return "Следить за динамикой, небольшая корректировка ставок"
    elif orders == 0:      return "Нет заказов — проверить настройки таргетинга"
    else:                  return "Кампания эффективна, можно масштабировать"

# ── Анализ рейтинга ──────────────────────────────────────
def analyze_ratings(nm_report: dict) -> list[RatingAlert]:
    alerts = []
    cards  = nm_report.get("data", {}).get("cards", [])
    for card in cards:
        nm     = card.get("nmID", 0)
        name   = (card.get("vendorCode")
                  or (card.get("object") or {}).get("name")
                  or f"#{nm}")
        r_now  = float((card.get("statistics") or {})
                       .get("selectedPeriod", {}).get("avgRating", 0) or 0)
        if r_now == 0:
            continue
        if r_now < RATING_CRITICAL:
            alerts.append(RatingAlert(nmId=nm, name=name, rating_now=r_now,
                severity="critical",
                message=f"Рейтинг {r_now:.1f}★ — {rating_label(r_now)}"))
        elif r_now < RATING_ACCEPTABLE:
            alerts.append(RatingAlert(nmId=nm, name=name, rating_now=r_now,
                severity="warning",
                message=f"Рейтинг {r_now:.1f}★ — {rating_label(r_now)}"))
    alerts.sort(key=lambda a: (0 if a.severity == "critical" else 1, a.rating_now))
    return alerts

# ── Анализ чистой прибыли ────────────────────────────────
def analyze_profit(weekly_report: list, adv_stats: list) -> list[ProfitItem]:
    costs = load_costs()
    by_nm: dict[int, dict] = defaultdict(lambda: {
        "name": "", "revenue": 0.0, "commission": 0.0,
        "logistics": 0.0, "storage": 0.0
    })
    for row in weekly_report:
        nm = int(row.get("nmId", 0) or 0)
        if nm == 0:
            continue
        by_nm[nm]["name"]        = _item_name(row, nm)
        by_nm[nm]["revenue"]    += float(row.get("retailAmount", 0) or row.get("ppvzForPay", 0) or 0)
        by_nm[nm]["commission"] += abs(float(row.get("commission_percent", 0) or 0))
        by_nm[nm]["logistics"]  += abs(float(row.get("deliveryAmount", 0) or 0))
        by_nm[nm]["storage"]    += abs(float(row.get("storageAmount", 0) or 0))

    adv_by_nm: dict[int, float] = defaultdict(float)
    for camp in adv_stats:
        nm_ids = camp.get("nmIds", [])
        spend  = sum(float(d.get("sum", 0)) for d in camp.get("days", []))
        if nm_ids:
            per_nm = spend / len(nm_ids)
            for nm in nm_ids:
                adv_by_nm[int(nm)] += per_nm

    result = []
    for nm, data in by_nm.items():
        revenue = data["revenue"]
        if revenue <= 0:
            continue
        cogs       = costs.get(nm, 0.0)
        commission = data["commission"]
        logistics  = data["logistics"]
        storage    = data["storage"]
        adv_cost   = adv_by_nm.get(nm, 0.0)
        expenses   = cogs + commission + logistics + storage + adv_cost
        profit_bt  = revenue - expenses
        tax        = max(profit_bt, 0) * TAX_RATE_USN
        net_profit = profit_bt - tax
        net_pct    = net_profit / revenue * 100
        drr_nm     = adv_cost / revenue * 100 if revenue > 0 else 0.0
        cogs_pct   = cogs / revenue * 100 if revenue > 0 else 0.0
        result.append(ProfitItem(
            nmId=nm, name=data["name"],
            revenue=revenue, cogs=cogs,
            wb_commission=commission, logistics=logistics,
            adv_cost=adv_cost, storage=storage,
            tax=tax, net_profit=net_profit,
            net_profit_pct=net_pct, needs_attention=(net_pct < MIN_PROFIT_PCT),
            recommendation=_profit_rec(net_pct, drr_nm, cogs_pct)
        ))
    result.sort(key=lambda p: p.net_profit_pct)
    return result


def _profit_rec(net_pct: float, drr: float, cogs_pct: float) -> str:
    if net_pct < 0:        return "Товар убыточен! Повысьте цену или снизьте рекламу"
    elif net_pct < 10:
        if drr > 10:       return f"ДРР {drr:.0f}% съедает прибыль — оптимизируйте рекламу"
        elif cogs_pct > 60:return "Высокая себестоимость — переговоры с поставщиком"
        else:              return "Низкая маржа — проверьте цену и скидки конкурентов"
    elif net_pct < 15:     return "ЧП ниже 15% — снизьте ДРР или чуть поднимите цену"
    else:                  return "Хорошая маржа — можно масштабировать"

# ── Утилиты ──────────────────────────────────────────────
def _parse_date(s) -> date:
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:
        return date(2000, 1, 1)
