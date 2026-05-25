import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
import requests

from config import STALE_DATA_DAKIKA

logger = logging.getLogger(__name__)

_fiyat_cache = {"alis": None, "satis": None, "zaman": 0}
_altin_cache = {"alis": None, "satis": None, "zaman": 0}
FIYAT_CACHE_SURE = 15

_MARKET_CONTEXT_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_MARKET_CONTEXT_TTL = 300.0
_SILVER_MTF_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_MTF_TTL = 300.0

TICKER_XAG = "SI=F"
TICKER_XAU = "GC=F"

_YF_INT_TO_TD = {
    "1m": "1min",
    "2m": "2min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "1d": "1day",
    "1wk": "1week",
    "1mo": "1month",
}


def _dunya_makas(alis, satis):
    if alis is not None and satis is not None:
        return round(float(satis) - float(alis), 4)
    return None


def _normalize_ohlcv_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or len(df) == 0:
        return None
    lmap = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    rename = {c: lmap[c.lower()] for c in df.columns if c.lower() in lmap}
    out = df.rename(columns=rename)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "Close" not in out.columns:
        return None
    return out.sort_index()


def get_silver_mtf(
    period_1m: str = "5d", period_5m: str = "1mo", period_15m: str = "2mo"
):
    del period_1m, period_5m, period_15m
    global _SILVER_MTF_CACHE
    now = time.time()
    t0 = float(_SILVER_MTF_CACHE.get("ts") or 0.0)
    if t0 and (now - t0) < _MTF_TTL:
        return _SILVER_MTF_CACHE["data"]

    import yfinance as yf

    try:
        df = yf.download("SI=F", period="5d", interval="15m", progress=False, auto_adjust=True)
        if df is not None and len(df) > 0:
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.index.name = "ts"
            o15 = _normalize_ohlcv_df(df)
        else:
            o15 = None
            logger.error("yfinance SI=F 15m verisi alınamadı.")
    except Exception as e:
        logger.error(f"yfinance MTF hatası: {e}")
        o15 = None

    try:
        df1h = yf.download("SI=F", period="60d", interval="1h", progress=False, auto_adjust=True)
        if df1h is not None and len(df1h) > 0:
            df1h.columns = [c[0] if isinstance(c, tuple) else c for c in df1h.columns]
            df1h.index.name = "ts"
            o1h = _normalize_ohlcv_df(df1h)
        else:
            o1h = None
    except Exception as e:
        logger.error(f"yfinance 1h hatası: {e}")
        o1h = None

    out: Dict[str, Any] = {"1m": None, "5m": None, "15m": o15, "1h": o1h}
    _SILVER_MTF_CACHE = {"data": out, "ts": now}
    return out


def get_xagusd_spot_last():
    try:
        import yfinance as yf
        df = yf.download("SI=F", period="1d", interval="1m", progress=False, auto_adjust=True)
        if df is not None and len(df) > 0:
            val = df["Close"].iloc[-1]
            if hasattr(val, 'item'):
                return float(val.item())
            return float(val)
    except Exception as e:
        logger.error(f"yfinance spot hatası: {e}")
    return None


def get_silver_price_dunyakatilim():
    global _fiyat_cache
    a0, s0 = _fiyat_cache.get("alis"), _fiyat_cache.get("satis")
    if (
        time.time() - _fiyat_cache["zaman"] < FIYAT_CACHE_SURE
        and a0 is not None
        and s0 is not None
    ):
        return a0, s0, _dunya_makas(a0, s0)
    try:
        r = requests.get(
            "https://dunyakatilim.com.tr/gunluk-kurlar",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        match = re.search(
            r"G&#xFC;m&#xFC;&#x15F;\s*\(XAG\).*?</td>.*?<td[^>]*>(\d+[.,]\d+)</td>.*?<td[^>]*>(\d+[.,]\d+)</td>",
            r.text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            alis = float(match.group(1).replace(",", "."))
            satis = float(match.group(2).replace(",", "."))
            makas = _dunya_makas(alis, satis)
            _fiyat_cache = {"alis": alis, "satis": satis, "zaman": time.time()}
            logger.info(f"Gümüş fiyatı: alış={alis}, satış={satis}, makas={makas}")
            return alis, satis, makas
        logger.error("Gümüş fiyatı regex eşleşmedi - HTML yapısı değişmiş olabilir")
        return None, None, None
    except Exception as e:
        logger.error(f"Dünya Katılım scraping hatası: {e}")
        a, s = _fiyat_cache.get("alis"), _fiyat_cache.get("satis")
        if a is not None and s is not None:
            return a, s, _dunya_makas(a, s)
        return None, None, None


def get_gold_price_dunyakatilim():
    global _altin_cache
    a0, s0 = _altin_cache.get("alis"), _altin_cache.get("satis")
    if (
        time.time() - _altin_cache["zaman"] < FIYAT_CACHE_SURE
        and a0 is not None
        and s0 is not None
    ):
        return a0, s0, _dunya_makas(a0, s0)
    try:
        r = requests.get(
            "https://dunyakatilim.com.tr/gunluk-kurlar",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        match = re.search(
            r"Alt&#x131;n\s*\(XAU\).*?</td>.*?<td[^>]*>(\d[.,]\d{3}[.,]\d{4})</td>.*?<td[^>]*>(\d[.,]\d{3}[.,]\d{4})</td>",
            r.text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            alis = float(match.group(1).replace(",", ""))
            satis = float(match.group(2).replace(",", ""))
            makas = _dunya_makas(alis, satis)
            _altin_cache = {"alis": alis, "satis": satis, "zaman": time.time()}
            logger.info(f"Altın fiyatı: alış={alis}, satış={satis}, makas={makas}")
            return alis, satis, makas
        logger.error("Altın fiyatı regex eşleşmedi - HTML yapısı değişmiş olabilir")
        return None, None, None
    except Exception as e:
        logger.error(f"Dünya Katılım altın scraping hatası: {e}")
        a, s = _altin_cache.get("alis"), _altin_cache.get("satis")
        if a is not None and s is not None:
            return a, s, _dunya_makas(a, s)
        return None, None, None


def get_market_context() -> Dict[str, Any]:
    global _MARKET_CONTEXT_CACHE
    now = time.time()
    t0 = float(_MARKET_CONTEXT_CACHE.get("ts") or 0.0)
    if t0 and (now - t0) < _MARKET_CONTEXT_TTL:
        return _MARKET_CONTEXT_CACHE["data"]
    ctx: Dict[str, Any] = {}
    try:
        import yfinance as yf
        df = yf.download("SI=F", period="5d", interval="1d", progress=False, auto_adjust=True)
        if df is not None and len(df) >= 2:
            c1 = float(df["Close"].iloc[-1].item())
            c0 = float(df["Close"].iloc[-2].item())
            ctx["gumus_degisim_yuzde"] = round((c1 - c0) / c0 * 100, 2) if c0 else 0.0
        else:
            ctx["gumus_degisim_yuzde"] = 0.0
    except Exception as e:
        logger.error(f"market context hatası: {e}")
        ctx["gumus_degisim_yuzde"] = 0.0
    _MARKET_CONTEXT_CACHE = {"data": ctx, "ts": now}
    return ctx