import logging
from datetime import datetime, timezone, time

import numpy as np
import pandas as pd

from core.data_engine import get_silver_data

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Indikatörler (pandas_ta YOK)
# ──────────────────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd = ema_fast - ema_slow
    sig = _ema(macd, signal)
    return macd - sig


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


def _vwap_intraday(df: pd.DataFrame) -> pd.Series:
    """
    Gün içi kümülatif VWAP:
    sum(typical_price * volume) / sum(volume), her gün sıfırlanır.
    """
    if "Volume" not in df.columns:
        return pd.Series(index=df.index, dtype=float)

    tp = (df["High"].astype(float) + df["Low"].astype(float) + df["Close"].astype(float)) / 3.0
    vol = df["Volume"].astype(float).clip(lower=0)

    idx = df.index
    if getattr(idx, "tz", None) is None:
        days = idx.normalize()
    else:
        days = idx.tz_convert(timezone.utc).normalize()

    pv = tp * vol
    cum_pv = pv.groupby(days).cumsum()
    cum_vol = vol.groupby(days).cumsum().replace(0, np.nan)
    return cum_pv / cum_vol


def _in_trade_window_utc(now: datetime) -> bool:
    """
    Londra penceresi: 06:00-09:00 UTC
    COMEX penceresi: 10:30-13:00 UTC
    """
    t = now.time()
    london = time(6, 0) <= t <= time(9, 0)
    comex = time(10, 30) <= t <= time(13, 0)
    return london or comex


# ──────────────────────────────────────────────────────────────
# Ana modül
# ──────────────────────────────────────────────────────────────

def calistir(config):
    """
    15dk + 1h kombinasyonu.

    Veri çekimi:
    - get_silver_data("15m", "5d")
    - get_silver_data("1h", "30d")

    Return formatı korunur:
    {"modul": "teknik", "puan": X, "fiyat_usd": X, "atr_1h": X}
    """
    try:
        df15 = get_silver_data(interval="15m", period="5d")
        df1h = get_silver_data(interval="1h", period="30d")
    except Exception as e:
        logger.error(f"Teknik veri çekme hatası: {e}")
        return {"modul": "teknik", "puan": 50, "detay": {}, "fiyat_usd": None, "atr_1h": None}

    if df15 is None or df1h is None or len(df15) < 60 or len(df1h) < 60:
        return {"modul": "teknik", "puan": 50, "detay": {}, "fiyat_usd": None, "atr_1h": None}

    df15 = df15.copy()
    df1h = df1h.copy()

    # 15m indikatörler
    close15 = df15["Close"].astype(float)
    df15["rsi14"] = _rsi(close15, 14)
    df15["macd_hist"] = _macd_hist(close15)
    df15["atr14"] = _atr(df15, 14)
    df15["vwap"] = _vwap_intraday(df15)
    if "Volume" in df15.columns:
        df15["vol_ma20"] = _sma(df15["Volume"].astype(float), 20)
    else:
        df15["vol_ma20"] = np.nan

    # 1h indikatörler
    close1h = df1h["Close"].astype(float)
    df1h["rsi14"] = _rsi(close1h, 14)
    df1h["ma50"] = _sma(close1h, 50)

    df15 = df15.dropna()
    df1h = df1h.dropna()
    if len(df15) < 5 or len(df1h) < 5:
        return {"modul": "teknik", "puan": 50, "detay": {}, "fiyat_usd": None, "atr_1h": None}

    l15 = df15.iloc[-1]
    p15 = df15.iloc[-2]
    l1h = df1h.iloc[-1]
    p1h = df1h.iloc[-2]
    p1h2 = df1h.iloc[-3] if len(df1h) >= 3 else p1h

    puan = 50

    # Puan kuralları
    ma50_up = bool(l1h["ma50"] > p1h["ma50"] and p1h["ma50"] > p1h2["ma50"])
    if ma50_up:
        puan += 20

    rsi_break = bool((30 <= p15["rsi14"] <= 40) and (l15["rsi14"] > 40) and (l15["rsi14"] > p15["rsi14"]))
    if rsi_break:
        puan += 25

    macd_flip = bool((p15["macd_hist"] < 0) and (l15["macd_hist"] > 0))
    if macd_flip:
        puan += 20

    vwap_ok = False
    if pd.notna(l15["vwap"]) and l15["vwap"] > 0:
        vwap_ok = bool(l15["Close"] <= l15["vwap"] * 1.003)
    if vwap_ok:
        puan += 15

    vol_spike = False
    if "Volume" in df15.columns and pd.notna(l15["vol_ma20"]) and l15["vol_ma20"] > 0:
        vol_spike = bool(float(l15["Volume"]) > float(l15["vol_ma20"]) * 1.5)
    if vol_spike:
        puan += 15

    now_utc = datetime.now(timezone.utc)
    window_ok = _in_trade_window_utc(now_utc)
    if window_ok:
        puan += 10

    puan = max(0, min(100, float(puan)))

    fiyat_usd = float(l15["Close"]) if pd.notna(l15["Close"]) else None
    atr15 = float(l15["atr14"]) if pd.notna(l15["atr14"]) else None

    detay = {
        "15m": {
            "fiyat": float(l15["Close"]),
            "rsi14": float(l15["rsi14"]),
            "macd_hist": float(l15["macd_hist"]),
            "atr14": float(l15["atr14"]),
            "vwap": float(l15["vwap"]) if pd.notna(l15["vwap"]) else None,
            "vol": float(l15["Volume"]) if "Volume" in df15.columns else None,
            "vol_ma20": float(l15["vol_ma20"]) if pd.notna(l15["vol_ma20"]) else None,
        },
        "1h": {
            "fiyat": float(l1h["Close"]),
            "rsi14": float(l1h["rsi14"]),
            "ma50": float(l1h["ma50"]),
        },
        "kurallar": {
            "ma50_1h_up": ma50_up,
            "rsi15_break_30_40_up": rsi_break,
            "macd_hist_15_flip_pos": macd_flip,
            "price_vs_vwap_15_ok": vwap_ok,
            "vol_spike_15": vol_spike,
            "trade_window_utc": window_ok,
        },
        "zaman_utc": now_utc.strftime("%H:%M"),
    }

    return {
        "modul": "teknik",
        "puan": round(puan, 1),
        "detay": detay,
        "fiyat_usd": fiyat_usd,
        # İstenen: 15dk ATR değerini `atr_1h` anahtarında döndür.
        "atr_1h": atr15,
    }
