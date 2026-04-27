"""
ДИАГНОСТИЧЕСКИЙ СКРИПТ — запустить ОДИН РАЗ через /debug команду.
Показывает сырые данные от WB API чтобы понять реальную структуру.
"""
import json
from wb_api import WBClient
import os

def run_debug(wb: WBClient) -> str:
    lines = ["🔍 *Диагностика WB API*\n"]

    # 1. Первый заказ — смотрим все поля
    orders = wb.get_orders(days_back=3)
    if orders:
        o = orders[0]
        lines.append("📦 *Поля заказа (первая запись):*")
        key_fields = ["nmId", "supplierArticle", "subject", "techSize",
                      "totalPrice", "discountPercent", "priceWithDisc",
                      "finishedPrice", "forPay", "date", "isCancel"]
        for k in key_fields:
            lines.append(f"  `{k}`: {o.get(k, '—')}")
        lines.append(f"  Всего заказов получено: {len(orders)}")
    else:
        lines.append("❌ Заказы: пустой ответ")

    lines.append("")

    # 2. Первая продажа
    sales = wb.get_sales(days_back=14)
    if sales:
        s = sales[0]
        lines.append("💰 *Поля продажи (первая запись):*")
        key_fields = ["nmId", "supplierArticle", "subject",
                      "totalPrice", "discountPercent", "priceWithDisc",
                      "forPay", "finishedPrice", "saleID", "date", "srid"]
        for k in key_fields:
            lines.append(f"  `{k}`: {s.get(k, '—')}")
        lines.append(f"  Всего продаж получено: {len(sales)}")
    else:
        lines.append("❌ Продажи: пустой ответ")

    lines.append("")

    # 3. Первый остаток
    stocks = wb.get_stocks()
    if stocks:
        st = stocks[0]
        lines.append("📦 *Поля остатка (первая запись):*")
        key_fields = ["nmId", "supplierArticle", "subject", "techSize",
                      "quantity", "quantityFull", "quantityNotInOrders",
                      "warehouseName", "lastChangeDate"]
        for k in key_fields:
            lines.append(f"  `{k}`: {st.get(k, '—')}")
        lines.append(f"  Всего строк остатков: {len(stocks)}")
        # Уникальные склады
        warehouses = set(s.get("warehouseName","") for s in stocks)
        lines.append(f"  Склады: {', '.join(list(warehouses)[:5])}")
    else:
        lines.append("❌ Остатки: пустой ответ")

    lines.append("")

    # 4. nm-report
    nm = wb.get_nm_report(days_back=7)
    cards = nm.get("data", {}).get("cards", []) if nm else []
    if cards:
        c = cards[0]
        lines.append("📊 *Поля nm-report (первая карточка):*")
        lines.append(f"  `nmID`: {c.get('nmID','—')}")
        lines.append(f"  `vendorCode`: {c.get('vendorCode','—')}")
        stats = c.get("statistics", {})
        period = stats.get("selectedPeriod", {})
        lines.append("  selectedPeriod:")
        for k, v in list(period.items())[:12]:
            lines.append(f"    `{k}`: {v}")
        lines.append(f"  Всего карточек: {len(cards)}")
    else:
        lines.append(f"❌ nm-report: пустой ответ. Raw: {str(nm)[:200]}")

    lines.append("")

    # 5. Рекламные кампании
    camp_ids = wb.get_campaign_ids()
    lines.append(f"📣 *Рекламные кампании:*")
    lines.append(f"  Найдено активных: {len(camp_ids)}")
    if camp_ids:
        adv = wb.get_adv_stats(camp_ids[:2])  # только первые 2
        if adv:
            a = adv[0]
            lines.append(f"  Пример кампании: {a.get('advertName','—')} (id: {a.get('advertId','—')})")
            days = a.get("days", [])
            if days:
                d = days[0]
                lines.append(f"  Поля дня: {list(d.keys())}")
                for k, v in list(d.items())[:8]:
                    lines.append(f"    `{k}`: {v}")
        else:
            lines.append("  ❌ Статистика кампаний: пустой ответ")
    else:
        lines.append("  ⚠ Кампании не найдены — проверьте WB_ADV_TOKEN")

    return "\n".join(lines)
