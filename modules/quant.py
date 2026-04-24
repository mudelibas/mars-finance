# --- Trend kuvveti: ADX-benzeri (5m) — 0–100 puan, düşük ADX = zayıf trend ---

import logging
import numpy as np
import pandas as pd
from core.data_engine import get_silver_mtf

logger = logging.getLogger(__name__)


def _tr(df):
    h, lo, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
    pc = c.shift(1)
    return pd.concat(
        [(h - lo), (h - pc).abs(), (lo - pc).abs()],
        axis=1,
    ).max(axis=1)


def _adx_ish(df, period=14):
    h, lo, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
    pdm = (h - h.shift(1)).where((h - h.shift(1)) > (lo.shift(1) - lo), 0.0).clip(0, None)
    ndm = (lo.shift(1) - lo).where((lo.shift(1) - lo) > (h - h.shift(1)), 0.0).clip(0, None)
    tr = _tr(df)
    atrp = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    pds = 100.0 * (pdm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atrp.replace(0, np.nan))
    nds = 100.0 * (ndm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atrp.replace(0, np.nan))
    dx = (abs(pds - nds) / (pds + nds + 1e-9)) * 100.0
    adx = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period * 2).mean()
    return pds, nds, adx, atrp


def calistir(config):
    try:
        m = get_silver_mtf()
        o5 = m.get("5m") if m else None
        if o5 is None or len(o5) < 60:
            return {
                "modul": "matematiksel",
                "puan": 0.0,
                "trend_strength": None,
                "detay": {},
            }
        pds, nds, adx, _ = _adx_ish(o5, 14)
        a = float(adx.values[-1]) if pd.notna(adx.values[-1]) else 0.0
        pdh, ndh = float(pds.values[-1]), float(nds.values[-1])
        puan = 40.0 + min(50.0, a * 0.55) if a > 15 else 25.0
        if pdh > ndh and float(o5["Close"].values[-1]) > float(
            o5["Close"].astype(float).ewm(span=20, adjust=False, min_periods=20).mean().values[-1]
        ):
            puan = min(100, puan + 10.0)
        puan = float(max(0, min(100, puan)))
        logger.info(
            f"[QUANT/ADX] adx~={a:.1f} +di={pdh:.1f} -di={ndh:.1f} puan={puan}"
        )
        return {
            "modul": "matematiksel",
            "puan": round(puan, 1),
            "trend_strength": round(a, 2),
            "detay": {"adx_proxy": a, "plus_di": pdh, "minus_di": ndh},
        }
    except Exception as e:
        logger.error(f"Quant/ADX: {e}")
        return {
            "modul": "matematiksel",
            "puan": 40.0,
            "trend_strength": None,
            "detay": {"hata": str(e)},
        }
