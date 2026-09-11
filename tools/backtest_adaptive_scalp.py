"""Backtest the adaptive scalp entry/exit rules using OHLC CSV data.

CSV columns required: timestamp,open,high,low,close
Additional columns are ignored. The model is deliberately conservative: signals
are generated from completed bars and filled at the next bar open.

Example:
    python tools/backtest_adaptive_scalp.py data.csv
"""
from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class Bar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float


@dataclass
class Trade:
    entry_time: str
    exit_time: str
    entry: float
    exit: float
    pct: float
    reason: str


def load_bars(path: Path) -> List[Bar]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = csv.DictReader(f)
        required = {"timestamp", "open", "high", "low", "close"}
        if not required.issubset(set(rows.fieldnames or [])):
            raise ValueError(f"CSV must contain {sorted(required)}")
        result = []
        for r in rows:
            result.append(
                Bar(
                    timestamp=str(r["timestamp"]),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                )
            )
    if len(result) < 50:
        raise ValueError("At least 50 bars are required.")
    return result


def true_range(curr: Bar, prev_close: float) -> float:
    return max(curr.high - curr.low, abs(curr.high - prev_close), abs(curr.low - prev_close))


def atr_series(bars: List[Bar], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(bars)
    trs: List[float] = []
    atr: Optional[float] = None
    for i, bar in enumerate(bars):
        if i == 0:
            prev_close = bar.close
            continue
        tr = true_range(bar, prev_close)
        prev_close = bar.close
        if atr is None:
            trs.append(tr)
            if len(trs) == period:
                atr = sum(trs) / period
                out[i] = atr
        else:
            atr = ((atr * (period - 1)) + tr) / period
            out[i] = atr
    return out


def adx_series(bars: List[Bar], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(bars)
    tr_sum = pdm_sum = ndm_sum = 0.0
    atr = pdm = ndm = None
    dx_values: List[float] = []
    adx = None
    for i in range(1, len(bars)):
        cur, prev = bars[i], bars[i - 1]
        tr = true_range(cur, prev.close)
        up = cur.high - prev.high
        down = prev.low - cur.low
        plus_dm = up if up > down and up > 0 else 0.0
        minus_dm = down if down > up and down > 0 else 0.0
        if atr is None:
            tr_sum += tr
            pdm_sum += plus_dm
            ndm_sum += minus_dm
            if i == period:
                atr = tr_sum / period
                pdm = pdm_sum / period
                ndm = ndm_sum / period
        else:
            atr = ((atr * (period - 1)) + tr) / period
            pdm = ((pdm * (period - 1)) + plus_dm) / period
            ndm = ((ndm * (period - 1)) + minus_dm) / period

        if atr is None or atr <= 0 or pdm is None or ndm is None:
            continue
        plus_di = 100.0 * pdm / atr
        minus_di = 100.0 * ndm / atr
        denom = plus_di + minus_di
        dx = 0.0 if denom <= 0 else 100.0 * abs(plus_di - minus_di) / denom
        if adx is None:
            dx_values.append(dx)
            if len(dx_values) >= period:
                adx = sum(dx_values[-period:]) / period
        else:
            adx = ((adx * (period - 1)) + dx) / period
        out[i] = adx
    return out


def max_drawdown(equity: List[float]) -> float:
    peak = equity[0] if equity else 1.0
    mdd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            mdd = min(mdd, value / peak - 1.0)
    return mdd


def run_backtest(
    bars: List[Bar],
    lookback: int = 5,
    breakout_buffer_pct: float = 0.15,
    momentum_bars: int = 3,
    min_volatility_pct: float = 0.12,
    max_chase_atr: float = 1.5,
    stop_atr: float = 1.0,
    trail_atr: float = 1.5,
    trail_arm_atr: float = 0.8,
    take_profit_atr: float = 1.8,
    take_profit_pct: float = 1.0,
    adx_threshold: float = 20.0,
    atr_period: int = 14,
    adx_period: int = 14,
) -> tuple[List[Trade], List[float]]:
    atr = atr_series(bars, atr_period)
    adx = adx_series(bars, adx_period)
    trades: List[Trade] = []
    equity = [1.0]
    in_pos = False
    entry = peak = 0.0
    entry_time = ""
    for i in range(max(lookback + momentum_bars + 2, adx_period * 2 + 1), len(bars) - 1):
        bar = bars[i]
        a = atr[i]
        d = adx[i]
        if a is None or a <= 0 or d is None:
            equity.append(equity[-1])
            continue

        if in_pos:
            peak = max(peak, bar.close)
            stop = entry - stop_atr * a
            trail = peak - trail_atr * a
            arm = entry + trail_arm_atr * a
            target = max(entry * (1 + take_profit_pct / 100.0), entry + take_profit_atr * a)
            reason = None
            exit_price = None
            if bar.low <= stop:
                reason, exit_price = "stop", stop
            elif peak >= arm and bar.low <= trail:
                reason, exit_price = "trail", trail
            elif bar.high >= target:
                reason, exit_price = "target", target
            if reason:
                next_open = bars[i + 1].open
                fill = min(next_open, exit_price) if reason == "stop" else max(next_open, exit_price) if reason == "target" else next_open
                pct = fill / entry - 1.0
                trades.append(Trade(entry_time, bars[i + 1].timestamp, entry, fill, pct, reason))
                equity.append(equity[-1] * (1.0 + pct))
                in_pos = False
                continue
            equity.append(equity[-1])
            continue

        previous_high = max(b.high for b in bars[i - lookback:i])
        breakout = max(previous_high * (1 + breakout_buffer_pct / 100.0), previous_high + 0.15 * a)
        recent_closes = [b.close for b in bars[i - momentum_bars:i + 1]]
        momentum_ok = all(recent_closes[j] < recent_closes[j + 1] for j in range(len(recent_closes) - 1))
        volatility = a / bar.close * 100.0 if bar.close > 0 else 0.0
        recent_low = min(b.low for b in bars[i - lookback:i])
        chase_ok = bar.close <= recent_low + max_chase_atr * a
        if bar.close >= breakout and momentum_ok and volatility >= min_volatility_pct and chase_ok and d >= adx_threshold:
            next_open = bars[i + 1].open
            entry = next_open
            peak = entry
            entry_time = bars[i + 1].timestamp
            in_pos = True
        equity.append(equity[-1])

    return trades, equity


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    bars = load_bars(args.csv)
    trades, equity = run_backtest(bars)
    wins = sum(t.pct > 0 for t in trades)
    total = math.prod(1.0 + t.pct for t in trades) - 1.0 if trades else 0.0
    avg = sum(t.pct for t in trades) / len(trades) if trades else 0.0
    mdd = max_drawdown(equity)
    print(f"bars={len(bars)} trades={len(trades)}")
    print(f"win_rate={wins/len(trades):.2%}" if trades else "win_rate=0.00%")
    print(f"total_return={total:.2%}")
    print(f"avg_trade={avg:.3%}")
    print(f"max_drawdown={mdd:.2%}")
    for t in trades[-10:]:
        print(f"{t.entry_time} -> {t.exit_time} {t.pct:.2%} {t.reason}")


if __name__ == "__main__":
    main()
