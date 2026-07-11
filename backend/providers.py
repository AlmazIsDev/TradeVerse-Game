"""Провайдеры реальных рыночных данных.

Архитектура:
    MarketDataService → CoinGeckoProvider → Database → Frontend

Ключи читаются ТОЛЬКО из окружения (.env):
    COINGECKO_API_KEY   — необязателен (без него используется public API CoinGecko)

Акции больше не тянут внешние котировки (см. stocks.py) — цена системных
акций двигается только объёмом сделок (игроки + боты), как и у пользовательских.

Все сетевые вызовы обёрнуты вызывающим кодом в try/except: при недоступности
API используются последние сохранённые значения из базы (см. MarketDataService).
"""
import logging
import os

logger = logging.getLogger("tradeverse.providers")

HTTP_TIMEOUT = 15.0


def _load_httpx():
    """Ленивая загрузка httpx — отсутствие пакета не должно ломать импорт модуля."""
    import httpx  # noqa: WPS433 (умышленно локальный импорт)
    return httpx


# ── CoinGecko (криптовалюты) ─────────────────────────────────────────────────


class CoinGeckoProvider:
    """Реальные данные криптовалют через CoinGecko.

    Public API не требует ключа. При наличии COINGECKO_API_KEY используется
    Pro-эндпоинт с соответствующим заголовком.
    """

    def __init__(self):
        self.api_key = os.getenv("COINGECKO_API_KEY")
        # CoinGecko различает Demo- и Pro-ключи: у них РАЗНЫЕ хосты и заголовки.
        #   Demo (бесплатный, префикс "CG-"): api.coingecko.com     + x-cg-demo-api-key
        #   Pro  (платный)                  : pro-api.coingecko.com + x-cg-pro-api-key
        # Отправка Demo-ключа на Pro-эндпоинт даёт 400 Bad Request. План берём из
        # COINGECKO_API_PLAN (demo|pro); по умолчанию — demo (частый случай).
        plan = (os.getenv("COINGECKO_API_PLAN") or "demo").strip().lower()
        if self.api_key and plan == "pro":
            self.base = "https://pro-api.coingecko.com/api/v3"
            self.headers = {"x-cg-pro-api-key": self.api_key}
        elif self.api_key:
            self.base = "https://api.coingecko.com/api/v3"
            self.headers = {"x-cg-demo-api-key": self.api_key}
        else:
            self.base = "https://api.coingecko.com/api/v3"
            self.headers = {}

    @property
    def available(self) -> bool:
        # CoinGecko доступен и без ключа.
        return True

    async def get_markets(self, per_page: int = 50) -> list[dict]:
        """Топ монет по капитализации. Возвращает нормализованный список."""
        httpx = _load_httpx()
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": max(1, min(per_page, 250)),
            "page": 1,
            "price_change_percentage": "24h",
        }
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(f"{self.base}/coins/markets", params=params, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()

        out = []
        for c in data:
            sym = (c.get("symbol") or "").upper()
            if not sym:
                continue
            out.append({
                "coingeckoId": c.get("id"),
                "symbol": sym,
                "name": c.get("name") or sym,
                "image": c.get("image"),
                "price": float(c.get("current_price") or 0.0),
                "marketCap": float(c.get("market_cap") or 0.0),
                "volume24h": float(c.get("total_volume") or 0.0),
                "change24h": float(c.get("price_change_percentage_24h") or 0.0),
                "supply": float(c.get("circulating_supply") or 0.0),
                "ath": float(c.get("ath") or 0.0),
                "atl": float(c.get("atl") or 0.0),
            })
        return out

    async def get_market_chart(self, coin_id: str, days: int = 365) -> list[tuple[float, float]]:
        """Реальная история цены монеты: список (unix_seconds, price)."""
        httpx = _load_httpx()
        params = {"vs_currency": "usd", "days": days}
        if days > 90:
            params["interval"] = "daily"
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{self.base}/coins/{coin_id}/market_chart", params=params, headers=self.headers,
            )
            resp.raise_for_status()
            data = resp.json()
        prices = data.get("prices", [])
        return [(ts / 1000.0, float(p)) for ts, p in prices]
