# --- XAGUSD: çoklu zaman (1m/5m/15m) trend sürdürme, EMA20/50, VWAP, HH/HL yapı ---

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core.data_engine import get_silver_mtf
import config as cfg

logger = logging.getLogger(__name__)


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _vwap(df: pd.DataFrame) -> pd.Series:
    if "Volume" not in df.columns:
        return (df["High"] + df["Low"] + df["Close"]) / 3.0
    h, lo, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
    tp = (h + lo + c) / 3.0
    v = df["Volume"].astype(float).clip(0.0, None)
    g = (df.index.normalize() if df.index.tz is None
         else df.index.tz_convert("UTC").normalize())
    pv = (tp * v).groupby(g).cumsum()
    vol = v.groupby(g).cumsum().replace(0, np.nan)
    return pv / vol


def _yapi_hh_hl_5m(df5, look=12):
    """Son swing’ler: iki dip yükseliyor ve son tepe tepeki ~ destek; Long sürdürme yönü."""
    if len(df5) < look + 2:
        return False
    lo = df5["Low"].astype(float)
    lo_win = lo.rolling(3, center=True).min()
    dps = [i for i in range(2, len(lo_win) - 2) if lo_win.iloc[i] == lo.iloc[i]
           and lo.iloc[i] < lo.iloc[i - 1] and lo.iloc[i] < lo.iloc[i + 1]]
    if len(dps) < 2:
        return float(df5["Close"].iloc[-1]) > float(df5["Close"].iloc[-6])
    return float(lo.iloc[dps[-1]]) > float(lo.iloc[dps[-2]])


def calistir(config):
    """
    15m: yönsel tercih (EMA20 > EMA50).
    5m: trend onayı + HH/HL.
    1m: EMA20/VWAP geri çekilme bölgesinde LİMİT mantığı, tetik = bu bantta kapanış.
    Dönüş/RSI tabanlı mean-reversion puanı YOK.
    """
    mtf = get_silver_mtf()
    o1, o5, o15 = mtf.get("1m"), mtf.get("5m"), mtf.get("15m")
    if o15 is None or o5 is None or o1 is None:
        return _bos("MTF yok")

    need15, need5, need1 = 55, 55, 30
    if len(o15) < need15 or len(o5) < need5 or len(o1) < need1:
        return _bos("MTF uzunluk yetersiz")

    e20f = int(config.get("EMA_TREND_HIZLI", 20))
    e50s = int(config.get("EMA_TREND_YAVAS", 50))

    c15 = o15["Close"].astype(float)
    c5 = o5["Close"].astype(float)
    c1 = o1["Close"].astype(float)

    e15_20, e15_50 = _ema(c15, e20f), _ema(c15, e50s)
    e5_20, e5_50 = _ema(c5, e20f), _ema(c5, e50s)
    e1_20 = _ema(c1, e20f)
    v1 = _vwap(o1).ffill()

    b15, b5, b1 = float(c15.values[-1]), float(c5.values[-1]), float(c1.values[-1])
    up15 = float(e15_20.values[-1]) > float(e15_50.values[-1]) and b15 > float(
        e15_20.values[-1]
    ) * 0.998
    up5 = float(e5_20.values[-1]) > float(e5_50.values[-1])
    yapi = _yapi_hh_hl_5m(o5)

    ve1, ee1 = float(v1.values[-1]), float(e1_20.values[-1])
    mxx, mnn = max(ve1, ee1), min(ve1, ee1)
    in_pull = mnn * 0.999 <= b1 <= mxx * 1.001
    chase = b1 > mxx * 1.004
    if chase:
        logger.info("[TEKNİK] 1m: kovala giriş — RED")

    puan = 0.0
    if not up15 or not up5 or not yapi:
        puan = 20.0
    elif not in_pull or chase:
        puan = 35.0
    else:
        puan = 88.0
        if b1 <= (mxx + mnn) / 2 * 1.0005:
            puan = min(100, puan + 8.0)

    fiyat = b1
    # Limit teklif fiyatı: EMA20 + VWAP orta bandı
    entry_limit = float(0.5 * (mxx + mnn))

    logger.info(
        f"[TEKNİK] 15/5 onay| up15={up15} up5={up5} yapi_hl={yapi} pull={in_pull} puan={puan}"
    )

    return {
        "modul": "teknik",
        "puan": round(puan, 1),
        "fiyat_usd": fiyat,
        "atr_1h": None,
        "trend_continuation": bool(up15 and up5 and yapi),
        "in_pullback_zone": bool(in_pull and not chase),
        "entry_limit_usd_oz": entry_limit,
        "detay": {
            "15m": f"EMA{e20f}/EMA{e50s}, long_bias={up15}",
            "5m": f"onay+HH/HL: up5={up5}, yapi={yapi}",
            "1m": f"EMA20={ee1:.4f} VWAP~={ve1:.4f} bantta={in_pull} chase={chase}",
        },
    }


def _bos(neden):
    return {
        "modul": "teknik",
        "puan": 0.0,
        "fiyat_usd": None,
        "atr_1h": None,
        "trend_continuation": False,
        "in_pullback_zone": False,
        "entry_limit_usd_oz": None,
        "detay": {"bos": neden},
    }
