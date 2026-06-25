"""
BIST Paper Trading Bot — MA Crossover Stratejisi
Gerçek para kullanılmaz; tüm işlemler simüle edilir.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Yapılandırma ──────────────────────────────────────────────────────────────

@dataclass
class BotConfig:
    symbols: list[str]          # İzlenecek hisse kodları, örn. ["THYAO", "GARAN"]
    short_window: int = 20      # Kısa MA periyodu (gün)
    long_window: int = 50       # Uzun MA periyodu (gün)
    initial_cash: float = 100_000.0   # Başlangıç bakiyesi (TL)
    position_size_pct: float = 0.10   # Her işlemde kullanılacak bakiye oranı
    stop_loss_pct: float = 0.05       # Zarar-kes eşiği (%5)
    take_profit_pct: float = 0.15     # Kâr-al eşiği (%15)


# ── Pozisyon ──────────────────────────────────────────────────────────────────

@dataclass
class Position:
    symbol: str
    quantity: int
    entry_price: float
    entry_date: str

    @property
    def cost(self) -> float:
        return self.quantity * self.entry_price


# ── Portföy ───────────────────────────────────────────────────────────────────

@dataclass
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)

    def equity(self, prices: dict[str, float]) -> float:
        stock_value = sum(
            pos.quantity * prices.get(pos.symbol, pos.entry_price)
            for pos in self.positions.values()
        )
        return self.cash + stock_value

    def log_trade(self, action: str, symbol: str, qty: int, price: float, reason: str):
        trade = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "symbol": symbol,
            "quantity": qty,
            "price": price,
            "reason": reason,
        }
        self.trades.append(trade)
        logger.info(
            "%s | %s x%d @ %.2f TL | %s", action, symbol, qty, price, reason
        )


# ── Teknik Göstergeler ────────────────────────────────────────────────────────

def simple_moving_average(prices: list[float], window: int) -> Optional[float]:
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window


def ma_crossover_signal(
    prices: list[float], short_w: int, long_w: int
) -> Optional[str]:
    """
    Önceki ve mevcut periyottaki MA çiftini karşılaştırır.
    Kısa MA uzun MA'yı yukarı keserse 'BUY', aşağı keserse 'SELL', aksi hâlde None.
    """
    if len(prices) < long_w + 1:
        return None

    prev_short = simple_moving_average(prices[:-1], short_w)
    prev_long = simple_moving_average(prices[:-1], long_w)
    curr_short = simple_moving_average(prices, short_w)
    curr_long = simple_moving_average(prices, long_w)

    if None in (prev_short, prev_long, curr_short, curr_long):
        return None

    if prev_short <= prev_long and curr_short > curr_long:
        return "BUY"
    if prev_short >= prev_long and curr_short < curr_long:
        return "SELL"
    return None


# ── Veri Katmanı ──────────────────────────────────────────────────────────────

class BISTDataProvider:
    """
    Fintables API üzerinden BIST fiyat verisi çeker.
    API anahtarı FINTABLES_API_KEY ortam değişkeninden okunur.
    """

    BASE_URL = "https://api.fintables.com"

    def __init__(self):
        self.api_key = os.getenv("FINTABLES_API_KEY", "")
        self.headers = {"Authorization": f"Api-Key {self.api_key}"}

    def fetch_daily_closes(self, symbol: str, limit: int = 100) -> list[float]:
        """Son `limit` günlük kapanış fiyatlarını döndürür."""
        url = f"{self.BASE_URL}/funds/{symbol}/price-history/"
        params = {"period": "1d", "limit": limit}
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            closes = [float(bar["close"]) for bar in data.get("results", [])]
            return closes
        except Exception as exc:
            logger.warning("Veri çekme hatası (%s): %s", symbol, exc)
            return []

    def current_price(self, symbol: str) -> Optional[float]:
        closes = self.fetch_daily_closes(symbol, limit=1)
        return closes[-1] if closes else None


# ── Strateji Motoru ───────────────────────────────────────────────────────────

class MACrossoverStrategy:
    def __init__(self, config: BotConfig, provider: BISTDataProvider):
        self.config = config
        self.provider = provider

    def evaluate(self, symbol: str) -> tuple[Optional[str], Optional[float]]:
        """(sinyal, güncel_fiyat) döndürür."""
        closes = self.provider.fetch_daily_closes(
            symbol, limit=self.config.long_window + 5
        )
        if not closes:
            return None, None
        signal = ma_crossover_signal(closes, self.config.short_window, self.config.long_window)
        return signal, closes[-1]


# ── Paper Trading Motoru ──────────────────────────────────────────────────────

class PaperTradingEngine:
    def __init__(self, config: BotConfig):
        self.config = config
        self.portfolio = Portfolio(cash=config.initial_cash)
        self.provider = BISTDataProvider()
        self.strategy = MACrossoverStrategy(config, self.provider)

    # ── İşlem Yürütücüler ─────────────────────────────────────────────────

    def _buy(self, symbol: str, price: float, reason: str):
        if symbol in self.portfolio.positions:
            logger.debug("%s zaten portföyde, alım atlandı.", symbol)
            return

        budget = self.portfolio.cash * self.config.position_size_pct
        qty = int(budget / price)
        if qty < 1:
            logger.warning("%s için yeterli nakit yok.", symbol)
            return

        cost = qty * price
        self.portfolio.cash -= cost
        self.portfolio.positions[symbol] = Position(
            symbol=symbol,
            quantity=qty,
            entry_price=price,
            entry_date=datetime.now().strftime("%Y-%m-%d"),
        )
        self.portfolio.log_trade("AL", symbol, qty, price, reason)

    def _sell(self, symbol: str, price: float, reason: str):
        pos = self.portfolio.positions.pop(symbol, None)
        if pos is None:
            logger.debug("%s portföyde yok, satım atlandı.", symbol)
            return

        proceeds = pos.quantity * price
        self.portfolio.cash += proceeds
        pnl = proceeds - pos.cost
        pnl_pct = pnl / pos.cost * 100
        self.portfolio.log_trade(
            "SAT", symbol, pos.quantity, price,
            f"{reason} | PNL: {pnl:+.2f} TL ({pnl_pct:+.1f}%)"
        )

    # ── Stop-Loss / Take-Profit ────────────────────────────────────────────

    def _check_exits(self, prices: dict[str, float]):
        for symbol, pos in list(self.portfolio.positions.items()):
            price = prices.get(symbol)
            if price is None:
                continue
            change = (price - pos.entry_price) / pos.entry_price
            if change <= -self.config.stop_loss_pct:
                self._sell(symbol, price, f"Stop-loss tetiklendi ({change:.1%})")
            elif change >= self.config.take_profit_pct:
                self._sell(symbol, price, f"Take-profit tetiklendi ({change:.1%})")

    # ── Ana Döngü ─────────────────────────────────────────────────────────

    def run_once(self):
        """Tüm sembolleri bir kez tarar, sinyal varsa işlem açar/kapatır."""
        logger.info("=== Tarama başlıyor — %d sembol ===", len(self.config.symbols))

        prices: dict[str, float] = {}
        for symbol in self.config.symbols:
            signal, price = self.strategy.evaluate(symbol)
            if price:
                prices[symbol] = price

            if signal == "BUY":
                self._buy(symbol, price, f"MA{self.config.short_window}/MA{self.config.long_window} yukarı kesiş")
            elif signal == "SELL" and symbol in self.portfolio.positions:
                self._sell(symbol, price, f"MA{self.config.short_window}/MA{self.config.long_window} aşağı kesiş")

        self._check_exits(prices)
        self._print_summary(prices)

    def _print_summary(self, prices: dict[str, float]):
        equity = self.portfolio.equity(prices)
        gain = equity - self.config.initial_cash
        logger.info(
            "── ÖZET ── Nakit: %.2f TL | Özsermaye: %.2f TL | Kâr/Zarar: %+.2f TL",
            self.portfolio.cash, equity, gain,
        )
        for symbol, pos in self.portfolio.positions.items():
            price = prices.get(symbol, pos.entry_price)
            pnl = (price - pos.entry_price) / pos.entry_price * 100
            logger.info(
                "  [%s] %d lot @ %.2f → %.2f TL (%+.1f%%)",
                symbol, pos.quantity, pos.entry_price, price, pnl,
            )

    def save_trades(self, path: str = "trades.json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.portfolio.trades, f, ensure_ascii=False, indent=2)
        logger.info("İşlem geçmişi kaydedildi: %s", path)


# ── Giriş Noktası ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    config = BotConfig(
        symbols=["THYAO", "GARAN", "AKBNK", "EREGL", "SISE", "KCHOL", "BIMAS", "TUPRS"],
        short_window=20,
        long_window=50,
        initial_cash=100_000.0,
        position_size_pct=0.10,
        stop_loss_pct=0.05,
        take_profit_pct=0.15,
    )

    engine = PaperTradingEngine(config)
    engine.run_once()
    engine.save_trades()
