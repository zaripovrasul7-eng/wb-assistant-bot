"""
Бизнес-логика: анализирует данные WB и формирует алерты.

Пороги ДРР:
  ≤6%   🟢 норма
  7–9%  🟡 следить
  10–12% 🔴 проблема
  >12%  🚨 критично — срочная аналитика

Пороги склада:
  21 день — предупреждение
  15 дней — срочно

Пороги рейтинга:
  ≥ 4.8  ✅ отлично
  4.7    🟢 хорошо
  4.6    🟡 допустимо
  < 4.5  🔴 критично

Падение заказов: 2 дня подряд
"""

import json
import os
from collections import defaultdict
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field

# ════════════════════════════════════════════════════════
#  Пороги
# ════════════════════════════════════════════════════════

DRR_GREEN    = 6.0
DRR_ORANGE   = 9.0
DRR_RED      = 12.0

STOCK_WARN_DAYS   = 21
STOCK_URGENT_DAYS = 15

ORDER_DROP_DAYS = 2
ORDER_DROP_PCT  = 20

RATING_CRITICAL    = 4.5   # ниже — критично 🔴
RATING_ACCEPTABLE  = 4.6   # допустимо 🟡
RATING_GOOD        = 4.7   # хорошо 🟢
RATING_EXCELLENT   = 4.8   # отлично ✅

MIN_PROFIT_PCT = 15.0      # ЧП ниже 15% — нужна рекомендация

TAX_RATE_USN = 0.07        # УСН 7%

# ════════════════════════════════════════════════════════
#  Эмодзи-помощники
# ════════════════════════════════════════════════════════

def drr_emoji(drr: float) -> str:
    if drr <= DRR_GREEN:   return "🟢"
    elif drr <= DRR_ORANGE: return "🟡"
    elif drr <= DRR_RED:    return "🔴"
    else:                   return "🚨"

def drr_label(drr: float) -> str:
    if drr <= DRR_GREEN:   return "норма"
    elif drr <= DRR_ORANGE: return "следить"
    elif drr <= DRR_RED:    return "проблема"
    else:                   return "СТОП — срочная аналитика"

def rating_emoji(r: float) -> str:
    if r >= RATING_EXCELLENT:  return "✅"
    elif r >= RATING_GOOD:     return "🟢"
    elif r >= RATING_ACCEPTABLE: return "🟡"
    else:                      return "🔴"

def rating_label(r: float) -> str:
    if r >= RATING_EXCELLENT:  return "отлично"
    elif r >= RATING_GOOD:     return "хорошо"
    elif r >= RATING_ACCEPTABLE: return "допустимо"
    else:                      return "критично"

# ════════════════════════════════════════════════════════
#  Структуры данных
# ════════════════════════════════════════════════════════

@dataclass
class DailyMetrics:
    orders_today:     int   = 0
    orders_yesterday: int   = 0
    revenue_today:    float = 0.0
    revenue_7d:       float = 0.0
    buyout_rate:      float = 0.0
    tacoo:            float = 0.0

@dataclass
class SKUAlert:
    nmId:       int
    name:       str
    alert_type: str   # 'drr' | 'stock' | 'orders'
    severity:   str   # 'warning' | 'critical'
    message:    str
    action:     str = ""

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
    nmId:          int
    name:          str
    revenue:       float
    cogs:          float        # себестоимость
    wb_commission: float        # комиссия WB
    logistics:     float        # логистика
    adv_cost:      float        # реклама
    storage:       float        # хранение
    tax:           float        # УСН 7%
    net_profit:    float        # чистая прибыль
    net_profit_pct: float       # ЧП %
    needs_attention: bool       # ЧП < 15%
    recommendation: str = ""

# ════════════════════════════════════════════════════════
#  Загрузка себестоимости
# ════════════════════════════════════════════════════════

def load_costs() -> dict[int, float]:
    """Загружает себестоимость из costs.json."""
    path = os.path.join(os.path.dirname(__file__), "costs.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {int(k): float(v) for k, v in data.get("costs", {}).items()}
    except Exception:
        return {}

# ════════════════════════════════════════════════════════
#  Анализ заказов
# ════════════════════════════════════════════════════════

def analyze_orders(orders: list) -> tuple[DailyMetrics, list[SKUAlert]]:
    today     = date.today()
    yesterday = today - timedelta(days=1)
    day_2ago  = today - timedelta(days=2)

    by_date_sku   = defaultdict(lambda: defaultdict(lambda: {"orders": 0, "revenue": 0.0, "name": ""}))
    by_date_total = defaultdict(lambda: {"orders": 0, "revenue": 0.0})

    for o in orders:
        try:
            o_date = datetime.fromisoformat(o.get("date", "")[:10]).date()
        except Exception:
            continue
        if o.get("isCancel"):
            continue
        nm   = o.get("nmId", 0)
        name = o.get("supplierArticle") or o.get("subject", f"#{nm}")
        rev  = float(o.get("totalPrice", 0)) * (1 - float(o.get("discountPercent", 0)) / 100)

        by_date_sku[o_date][nm]["orders"]  += 1
        by_date_sku[o_date][nm]["revenue"] += rev
        by_date_sku[o_date][nm]["name"]     = name
        by_date_total[o_date]["orders"]    += 1
        by_date_total[o_date]["revenue"]   += rev

    metrics = DailyMetrics(
        orders_today     = by_date_total[today]["orders"],
        orders_yesterday = by_date_total[yesterday]["orders"],
        revenue_today    = by_date_total[today]["revenue"],
    )

    alerts = []
    for nm in set(by_date_sku[yesterday]) | set(by_date_sku[day_2ago]):
        cnt_y = by_date_sku[yesterday][nm]["orders"]
        cnt_2 = by_date_sku[day_2ago][nm]["orders"]
        name  = by_date_sku[yesterday][nm]["name"] or by_date_sku[day_2ago][nm]["name"] or f"Арт. #{nm}"
        if cnt_2 == 0:
            continue
        drop_pct = (cnt_2 - cnt_y) / cnt_2 * 100
        if drop_pct >= ORDER_DROP_PCT and cnt_y < cnt_2:
            severity = "critical" if drop_pct >= 50 else "warning"
            alerts.append(SKUAlert(
                nmId=nm, name=name, alert_type="orders", severity=severity,
                message=f"Заказы −{drop_pct:.0f}% за 2 дня ({cnt_2}→{cnt_y} шт.)",
                action="Проверьте позиции в поиске и цены конкурентов"
            ))
    return metrics, alerts

# ════════════════════════════════════════════════════════
#  Анализ остатков
# ════════════════════════════════════════════════════════

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
            names[nm] = o.get("supplierArticle") or o.get("subject", f"#{nm}")

    stock_map = defaultdict(int)
    for s in stocks:
        nm = s.get("nmId", 0)
        stock_map[nm] += int(s.get("quantity", 0))
        if nm not in names:
            names[nm] = s.get("supplierArticle") or s.get("subject", f"#{nm}")

    alerts = []
    for nm, total in stock_map.items():
        avg = sales_7d.get(nm, 0) / 7
        if avg < 0.01:
            continue
        days = total / avg
        name = names.get(nm, f"Арт. #{nm}")
        if days <= STOCK_URGENT_DAYS:
            alerts.append(SKUAlert(
                nmId=nm, name=name, alert_type="stock", severity="critical",
                message=f"Остаток на {days:.0f} дней ({total} шт.)",
                action="Срочно отправьте поставку!"
            ))
        elif days <= STOCK_WARN_DAYS:
            alerts.append(SKUAlert(
                nmId=nm, name=name, alert_type="stock", severity="warning",
                message=f"Остаток на {days:.0f} дней ({total} шт.)",
                action="Запланируйте поставку"
            ))
    return sorted(alerts, key=lambda a: 0 if a.severity == "critical" else 1)

# ════════════════════════════════════════════════════════
#  Анализ рекламы
# ════════════════════════════════════════════════════════

def analyze_adv(adv_stats: list) -> tuple[float, list[AdvCampaignInfo], list[SKUAlert]]:
    campaigns = []
    total_spend = total_rev = 0.0

    for camp in adv_stats:
        cid  = camp.get("advertId", 0)
        name = camp.get("advertName", f"Кампания #{cid}")
        spend = orders = revenue = days_count = 0
        for d in camp.get("days", []):
            spend    += float(d.get("sum", 0))
            orders   += int(d.get("orders", 0))
            revenue  += float(d.get("sum_price", 0))
            days_count += 1

        drr = (spend / revenue * 100) if revenue > 0 else (999.0 if spend > 0 else 0.0)
        avg_spend = spend / max(days_count, 1)

        rec = _adv_recommendation(drr, orders)

        campaigns.append(AdvCampaignInfo(
            campaign_id=cid, name=name, drr=drr,
            spend_per_day=avg_spend, orders=orders, recommendation=rec
        ))
        total_spend += spend
        total_rev   += revenue

    tacoo = (total_spend / total_rev * 100) if total_rev > 0 else 0.0

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
    return tacoo, campaigns, alerts


def _adv_recommendation(drr: float, orders: int) -> str:
    if drr > DRR_RED:
        return "Приостановить кампанию, провести аналитику ключевых запросов"
    elif drr > DRR_ORANGE:
        return "Снизить ставки на 20–30%, убрать нерабочие ключи"
    elif drr > DRR_GREEN:
        return "Следить за динамикой, небольшая корректировка ставок"
    elif orders == 0:
        return "Нет заказов — проверить настройки таргетинга"
    else:
        return "Кампания эффективна, можно масштабировать"

# ════════════════════════════════════════════════════════
#  Анализ рейтинга
# ════════════════════════════════════════════════════════

def analyze_ratings(nm_report: dict) -> list[RatingAlert]:
    """
    Пороги: <4.5 критично 🔴 | 4.6 допустимо 🟡 | 4.7 хорошо 🟢 | ≥4.8 отлично ✅
    """
    alerts = []
    cards  = nm_report.get("data", {}).get("cards", [])

    for card in cards:
        nm   = card.get("nmID", 0)
        name = card.get("vendorCode", f"Арт. #{nm}")
        if card.get("object"):
            name = card["object"].get("name", name)

        stats  = card.get("statistics", {})
        r_now  = float(stats.get("selectedPeriod", {}).get("avgRating", 0) or 0)

        if r_now == 0:
            continue

        if r_now < RATING_CRITICAL:
            alerts.append(RatingAlert(
                nmId=nm, name=name, rating_now=r_now,
                severity="critical",
                message=f"Рейтинг {r_now:.1f}★ — {rating_label(r_now)}"
            ))
        elif r_now < RATING_ACCEPTABLE:
            alerts.append(RatingAlert(
                nmId=nm, name=name, rating_now=r_now,
                severity="warning",
                message=f"Рейтинг {r_now:.1f}★ — {rating_label(r_now)}"
            ))

    alerts.sort(key=lambda a: (0 if a.severity == "critical" else 1, a.rating_now))
    return alerts

# ════════════════════════════════════════════════════════
#  Анализ чистой прибыли
# ════════════════════════════════════════════════════════

def analyze_profit(weekly_report: list, adv_stats: list) -> list[ProfitItem]:
    """
    Считает чистую прибыль по каждому артикулу.
    Формула: Выручка − Себестоимость − Комиссия WB − Логистика − Реклама − Хранение − УСН 7%
    """
    costs = load_costs()

    # Группируем недельный отчёт по nmId
    by_nm: dict[int, dict] = defaultdict(lambda: {
        "name": "", "revenue": 0.0, "commission": 0.0,
        "logistics": 0.0, "storage": 0.0
    })

    for row in weekly_report:
        nm   = int(row.get("nmId", 0) or 0)
        if nm == 0:
            continue
        name = row.get("supplierArticle") or row.get("subject", f"#{nm}")
        by_nm[nm]["name"]       = name
        # Выручка = цена продажи (retailAmount) или totalPrice
        by_nm[nm]["revenue"]   += float(row.get("retailAmount", 0) or row.get("ppvzForPay", 0) or 0)
        by_nm[nm]["commission"]+= abs(float(row.get("commission_percent", 0) or 0))
        by_nm[nm]["logistics"] += abs(float(row.get("deliveryAmount", 0) or 0))
        by_nm[nm]["storage"]   += abs(float(row.get("storageAmount", 0) or 0))

    # Рекламные расходы по nm (из adv_stats, связываем через advertId если есть nmId)
    adv_by_nm: dict[int, float] = defaultdict(float)
    for camp in adv_stats:
        nm_ids = camp.get("nmIds", [])
        total_spend = sum(float(d.get("sum", 0)) for d in camp.get("days", []))
        if nm_ids:
            per_nm = total_spend / len(nm_ids)
            for nm in nm_ids:
                adv_by_nm[int(nm)] += per_nm

    result = []
    for nm, data in by_nm.items():
        revenue   = data["revenue"]
        if revenue <= 0:
            continue
        cogs      = costs.get(nm, 0.0)
        commission= data["commission"]
        logistics = data["logistics"]
        storage   = data["storage"]
        adv_cost  = adv_by_nm.get(nm, 0.0)

        expenses  = cogs + commission + logistics + storage + adv_cost
        profit_before_tax = revenue - expenses
        tax       = max(profit_before_tax, 0) * TAX_RATE_USN
        net_profit= profit_before_tax - tax
        net_pct   = (net_profit / revenue * 100) if revenue > 0 else 0.0
        needs_att = net_pct < MIN_PROFIT_PCT

        rec = _profit_recommendation(net_pct, drr=(adv_cost/revenue*100 if revenue > 0 else 0),
                                     cogs_pct=(cogs/revenue*100 if revenue > 0 else 0))

        result.append(ProfitItem(
            nmId=nm, name=data["name"],
            revenue=revenue, cogs=cogs,
            wb_commission=commission, logistics=logistics,
            adv_cost=adv_cost, storage=storage,
            tax=tax, net_profit=net_profit,
            net_profit_pct=net_pct, needs_attention=needs_att,
            recommendation=rec
        ))

    result.sort(key=lambda p: p.net_profit_pct)
    return result


def _profit_recommendation(net_pct: float, drr: float, cogs_pct: float) -> str:
    if net_pct < 0:
        return "Товар убыточен! Повысьте цену или снизьте расходы на рекламу"
    elif net_pct < 10:
        if drr > 10:
            return f"ДРР {drr:.0f}% съедает прибыль — оптимизируйте рекламу или поднимите цену"
        elif cogs_pct > 60:
            return "Высокая себестоимость — рассмотрите переговоры с поставщиком"
        else:
            return "Низкая маржа — проверьте цену и скидки конкурентов"
    elif net_pct < 15:
        return "ЧП ниже 15% — можно улучшить: снизьте ДРР или незначительно поднимите цену"
    else:
        return "Хорошая маржинальность — можно масштабировать"


# ════════════════════════════════════════════════════════
#  Расчёт выкупа
# ════════════════════════════════════════════════════════

def calc_buyout_rate(orders: list, sales: list) -> float:
    today = date.today()
    order_count = sum(
        1 for o in orders
        if not o.get("isCancel")
        and _parse_date(o.get("date")) >= today - timedelta(days=14)
    )
    sale_count = sum(
        1 for s in sales
        if _parse_date(s.get("date")) >= today - timedelta(days=14)
    )
    return min(sale_count / order_count * 100, 100.0) if order_count > 0 else 0.0


def _parse_date(s) -> date:
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:
        return date(2000, 1, 1)
