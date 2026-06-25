"""
Geçmiş veri üzerinde MA Crossover stratejisini geriye dönük test eder.
Kullanım: python backtest.py
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from bot import BotConfig, ma_crossover_signal, simple_moving_average

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    symbol: str
    trades: list[dict] = field(default_factory=list)
    initial_cash: float = 100_000.0
    cash: float = 100_000.0
    position: int = 0
    entry_price: float = 0.0

    @property
    def total_return_pct(self) -> float:
        return (self.cash - self.initial_cash) / self.initial_cash * 100

    @property
    def win_count(self) -> int:
        return sum(1 for t in self.trades if t["pnl"] > 0)

    @property
    def loss_count(self) -> int:
        return sum(1 for t in self.trades if t["pnl"] <= 0)


def run_backtest(
    symbol: str,
    closes: list[float],
    short_window: int = 20,
    long_window: int = 50,
    initial_cash: float = 100_000.0,
    position_size_pct: float = 0.10,
    stop_loss_pct: float = 0.05,
    take_profit_pct: float = 0.15,
) -> BacktestResult:
    result = BacktestResult(symbol=symbol, initial_cash=initial_cash, cash=initial_cash)

    for i in range(long_window + 1, len(closes)):
        window = closes[: i + 1]
        price = closes[i]
        signal = ma_crossover_signal(window, short_window, long_window)

        # Stop-loss / take-profit kontrolü
        if result.position > 0:
            change = (price - result.entry_price) / result.entry_price
            if change <= -stop_loss_pct:
                signal = "SELL"
            elif change >= take_profit_pct:
                signal = "SELL"

        if signal == "BUY" and result.position == 0:
            budget = result.cash * position_size_pct
            qty = int(budget / price)
            if qty > 0:
                result.cash -= qty * price
                result.position = qty
                result.entry_price = price

        elif signal == "SELL" and result.position > 0:
            proceeds = result.position * price
            pnl = proceeds - result.position * result.entry_price
            result.trades.append(
                {
                    "bar": i,
                    "price": price,
                    "qty": result.position,
                    "pnl": pnl,
                    "return_pct": pnl / (result.position * result.entry_price) * 100,
                }
            )
            result.cash += proceeds
            result.position = 0
            result.entry_price = 0.0

    # Açık pozisyonu son fiyata kapat
    if result.position > 0:
        price = closes[-1]
        proceeds = result.position * price
        pnl = proceeds - result.position * result.entry_price
        result.trades.append(
            {
                "bar": len(closes) - 1,
                "price": price,
                "qty": result.position,
                "pnl": pnl,
                "return_pct": pnl / (result.position * result.entry_price) * 100,
                "note": "kapanış",
            }
        )
        result.cash += proceeds
        result.position = 0

    return result


def print_report(result: BacktestResult):
    print(f"\n{'='*50}")
    print(f"  BACKTEST SONUCU — {result.symbol}")
    print(f"{'='*50}")
    print(f"  Başlangıç : {result.initial_cash:>12,.2f} TL")
    print(f"  Bitiş     : {result.cash:>12,.2f} TL")
    print(f"  Toplam Kâr: {result.cash - result.initial_cash:>+12,.2f} TL  ({result.total_return_pct:+.1f}%)")
    print(f"  İşlem Sayısı: {len(result.trades)}  (Kâr: {result.win_count} / Zarar: {result.loss_count})")
    if result.trades:
        best = max(result.trades, key=lambda t: t["pnl"])
        worst = min(result.trades, key=lambda t: t["pnl"])
        print(f"  En İyi    : {best['pnl']:>+10,.2f} TL ({best['return_pct']:+.1f}%)")
        print(f"  En Kötü   : {worst['pnl']:>+10,.2f} TL ({worst['return_pct']:+.1f}%)")
    print()


# ─── Örnek: Sentetik veriyle hızlı test ──────────────────────────────────────

if __name__ == "__main__":
    import math
    import random

    random.seed(42)

    # Gerçek bir API yokken sentetik fiyat serisi oluştur
    def synthetic_prices(n: int = 300, start: float = 100.0) -> list[float]:
        prices = [start]
        for _ in range(n - 1):
            drift = 0.0003
            vol = 0.015
            r = drift + vol * random.gauss(0, 1)
            prices.append(round(prices[-1] * math.exp(r), 2))
        return prices

    for sym in ["THYAO_sim", "GARAN_sim", "EREGL_sim"]:
        closes = synthetic_prices(300, start=random.uniform(50, 300))
        result = run_backtest(sym, closes)
        print_report(result)

    print("Not: Gerçek BIST verisi için FINTABLES_API_KEY ortam değişkenini set edip bot.py üzerinden çalıştırın.")
