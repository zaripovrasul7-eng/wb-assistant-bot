"""
Модуль для работы с API Wildberries.
Использует ТОЛЬКО чтение — никаких изменений в вашем кабинете.
"""

import requests
from datetime import datetime, timedelta, date
import logging

logger = logging.getLogger(__name__)


class WBClient:
    """Клиент для работы с API Wildberries (только чтение)."""

    STATS_BASE = "https://statistics-api.wildberries.ru"
    ADV_BASE   = "https://advert-api.wildberries.ru"

    def __init__(self, stats_token: str, adv_token: str):
        self.stats_token = stats_token
        self.adv_token   = adv_token

    # ───────────────────────── вспомогательное ─────────────────────────

    def _stats_headers(self):
        return {"Authorization": self.stats_token}

    def _adv_headers(self):
        return {"Authorization": self.adv_token}

    def _get(self, base: str, path: str, token_type: str, params: dict = None):
        url     = base + path
        headers = self._stats_headers() if token_type == "stats" else self._adv_headers()
        try:
            r = requests.get(url, headers=headers, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"WB API error [{path}]: {e}")
            return None

    def _post(self, base: str, path: str, payload):
        url = base + path
        try:
            r = requests.post(url, headers=self._adv_headers(), json=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"WB API POST error [{path}]: {e}")
            return None

    # ───────────────────────── заказы ─────────────────────────

    def get_orders(self, days_back: int = 3) -> list:
        """Заказы за последние N дней."""
        date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00")
        data = self._get(self.STATS_BASE, "/api/v1/supplier/orders", "stats",
                         params={"dateFrom": date_from, "flag": 0})
        return data if isinstance(data, list) else []

    # ───────────────────────── продажи ─────────────────────────

    def get_sales(self, days_back: int = 2) -> list:
        """Продажи (выкупы) за последние N дней."""
        date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00")
        data = self._get(self.STATS_BASE, "/api/v1/supplier/sales", "stats",
                         params={"dateFrom": date_from, "flag": 0})
        return data if isinstance(data, list) else []

    # ───────────────────────── остатки ─────────────────────────

    def get_stocks(self) -> list:
        """Текущие остатки на складах WB. Поддерживает пагинацию (лимит 60к строк)."""
        date_from = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
        all_stocks = []
        last_change_date = date_from
        while True:
            data = self._get(self.STATS_BASE, "/api/v1/supplier/stocks", "stats",
                             params={"dateFrom": last_change_date})
            if not isinstance(data, list) or len(data) == 0:
                break
            all_stocks += data
            if len(data) < 60000:
                break   # получили все строки
            # Берём дату последней записи для следующей страницы
            last_change_date = data[-1].get("lastChangeDate", last_change_date)
            import time; time.sleep(1)  # соблюдаем лимит 1 запрос/мин
        return all_stocks

    # ───────────────────────── реклама ─────────────────────────

    def get_campaigns(self) -> dict:
        """Список активных рекламных кампаний."""
        data = self._get(self.ADV_BASE, "/adv/v1/promotion/count", "adv")
        return data if isinstance(data, dict) else {}

    def get_campaign_ids(self) -> list[int]:
        """ID всех активных кампаний (статус 7 = идёт, 9 = готова)."""
        # Статусы: 7 — кампания идёт, 9 — завершена, 11 — пауза
        active = []
        for status in (7, 11):  # активные + на паузе (нужно следить)
            data = self._get(self.ADV_BASE, "/adv/v1/promotion/adverts", "adv",
                             params={"status": status, "type": 8, "limit": 100})
            if isinstance(data, list):
                active += [item.get("advertId") for item in data if item.get("advertId")]
        return active

    def get_adv_stats(self, campaign_ids: list[int]) -> list:
        """
        Статистика рекламных кампаний за последние 3 дня.
        Возвращает список с расходами и заказами по каждой кампании.
        """
        if not campaign_ids:
            return []
        date_to   = date.today().isoformat()
        date_from = (date.today() - timedelta(days=3)).isoformat()

        # WB принимает максимум 100 кампаний за раз
        result = []
        for i in range(0, len(campaign_ids), 100):
            chunk   = campaign_ids[i:i+100]
            payload = [{"id": cid, "dates": [date_from, date_to]} for cid in chunk]
            data    = self._post(self.ADV_BASE, "/adv/v2/fullstats", payload)
            if isinstance(data, list):
                result += data
        return result

    # ───────────────────────── финансы ─────────────────────────

    def get_nm_report(self, days_back: int = 7) -> dict:
        """
        Отчёт по каждому артикулу (nm-report) через подписку Джем.
        Содержит: заказы, выкуп, конверсию, рейтинг товара.
        """
        date_to   = date.today().isoformat()
        date_from = (date.today() - timedelta(days=days_back)).isoformat()
        url = "https://seller-analytics-api.wildberries.ru/api/v2/nm-report/day"
        headers = {"Authorization": self.stats_token}
        payload = {
            "period": {"begin": date_from, "end": date_to},
            "timezone": "Europe/Moscow",
            "page": 1
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"WB nm-report error: {e}")
            return {}

    def get_weekly_report(self) -> list:
        """Финансовый еженедельный отчёт WB."""
        date_from = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%dT00:00:00")
        date_to   = datetime.now().strftime("%Y-%m-%dT23:59:59")
        data = self._get(self.STATS_BASE, "/api/v5/supplier/reportDetailByPeriod", "stats",
                         params={"dateFrom": date_from, "dateTo": date_to, "limit": 100000})
        return data if isinstance(data, list) else []
