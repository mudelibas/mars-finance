import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
import requests
from twelvedata import TDClient

from config import STALE_DATA_DAKIKA, TWELVEDATA_API_KEY

logger = logging.getLogger(__name__)

_fiyat_cache = {"alis": None, "satis": None, "zaman": 0}
_altin_cache = {"alis": None, "satis": None, "zaman": 0}
FIYAT_CACHE_SURE = 15

_MARKET_CONTEXT_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_MARKET_CONTEXT_TTL = 300.0
_SILVER_MTF_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_MTF_TTL = 300.0
_USDTRY_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_USDTRY_TTL = 60.0

# Yahoo-tarzı emtia/sembol isimlerinden Twelve Data sembollerine (SI=F / GC=F COMEX)
TICKER_XAG = "SI=F"
TICKER_XAU = "GC=F"
TD_SYMBOL = {
    "SI=F": "SI",
    "GC=F": "GC",
    "DX-Y.NYB": "DXY",
    "^TNX": "TNX",
    "^VIX": "VIX",
    "^GSPC": "SPX",
    "BZ=F": "BRN",
    "USDTRY=X": "USD/TRY",
}

# yfinance aralık → Twelve Data
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


def _get_td_client() -> Optional[TDClient]:
    if not TWELVEDATA_API_KEY:
        logger.error("TWELVEDATA_API_KEY tanımlı değil")
        return None
    return TDClient(apikey=TWELVEDATA_API_KEY)


def _yf_interval_to_td(yf_interval: str) -> str:
    m = _YF_INT_TO_TD.get(yf_interval)
    if m is not None:
        return m
    return yf_interval


def _period_to_outputsize(period: str, yf_interval: str) -> int:
    """Yaklaşık barmış gibi: yf period/interval → outputsize (1–5000, üst sınır 5000)."""
    p = (period or "1mo").lower()
    num = 30
    if p.endswith("d"):
        try:
            num = int(p.replace("d", ""))
        except ValueError:
            num = 5
    elif p.endswith("mo"):
        try:
            num = 30 * int(p.replace("mo", ""))
        except ValueError:
            num = 30
    elif p.endswith("y") or p.endswith("yr"):
        try:
            num = 365 * int(re.sub(r"[^0-9]", "", p) or 1)
        except ValueError:
            num = 90
    intv = (yf_interval or "1d").lower()
    if intv in ("1m", "2m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"):
        bars = {"1m": 390, "5m": 78, "15m": 26, "1h": 24, "1d": 1}.get(intv, 24) * num
    else:
        bars = num
    return int(max(5, min(5000, bars if bars > 0 else 30)))


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


def _td_ohlcv(
    yahoo_like_symbol: str,
    yf_interval: str,
    outputsize: int,
    order: str = "asc",
) -> Optional[pd.DataFrame]:
    td_sym = TD_SYMBOL.get(yahoo_like_symbol, yahoo_like_symbol)
    int_td = _yf_interval_to_td(yf_interval)
    if int_td not in {
        "1min",
        "2min",
        "5min",
        "15min",
        "30min",
        "45min",
        "1h",
        "2h",
        "4h",
        "8h",
        "1day",
        "1week",
        "1month",
    }:
        int_td = "1day" if (yf_interval or "1d") in ("1d", "1day") else "5min"
    client = _get_td_client()
    if not client:
        return None
    try:
        ts = client.time_series(
            symbol=td_sym,
            interval=int_td,
            outputsize=min(5000, max(1, int(outputsize))),
            order=order,
            timezone="UTC",
        )
        df = ts.as_pandas()
    except Exception as e:
        logger.error(f"Twelve Data time_series hata ({td_sym} {int_td}): {e}")
        return None
    if df is None or len(df) == 0:
        return None
    out = _normalize_ohlcv_df(df)
    if out is None or len(out) < 1:
        return None
    son_zaman = out.index[-1]
    if hasattr(son_zaman, "tzinfo") and son_zaman.tzinfo is None:
        son_zaman = son_zaman.tz_localize("UTC")
    gecen = (datetime.now(timezone.utc) - son_zaman).total_seconds() / 60
    if yf_interval in ("5m", "15m") and gecen > STALE_DATA_DAKIKA:
        logger.warning(
            f"{td_sym} ({yf_interval}) verisi {gecen:.0f} dk eski (eşik {STALE_DATA_DAKIKA})."
        )
    return out


def _indir(ticker, period, yf_interval):
    """
    Eski yfinance sözleşmesi: (ticker, period, yf aralığı) → OHLCV DataFrame.
    Artık Twelve Data kullanır; ticker Yahoo benzeri (örn. ^TNX, GC=F) olabilir.
    """
    osz = _period_to_outputsize(period, yf_interval)
    return _td_ohlcv(ticker, yf_interval, osz, order="asc")


def get_silver_mtf(
    period_1m: str = "5d", period_5m: str = "1mo", period_15m: str = "2mo"
):
    """
    15m: yfinance (SI=F) üzerinden 500 mum.
    1m ve 5m artık kullanılmıyor, None döner.
    Dönen: {"1m": None, "5m": None, "15m": df}
    Sonuç 300 sn boyunca in-memory cache'ten servis edilir.
    """
    del period_1m, period_5m, period_15m
    global _SILVER_MTF_CACHE
    now = time.time()
    t0 = float(_SILVER_MTF_CACHE.get("ts") or 0.0)
    if t0 and (now - t0) < _MTF_TTL:
        return _SILVER_MTF_CACHE["data"]
    try:
        import yfinance as yf
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
    out: Dict[str, Any] = {"1m": None, "5m": None, "15m": o15}
    _SILVER_MTF_CACHE = {"data": out, "ts": now}
    return out


def get_xau_5m(period: str = "1mo"):
    del period
    return _td_ohlcv(TICKER_XAU, "5m", 500, order="asc")


def get_xagusd_spot_last():
    """SI (USD/oz) son kapanış — yfinance."""
    try:
        import yfinance as yf
        df = yf.download("SI=F", period="1d", interval="1m", progress=False, auto_adjust=True)
        if df is not None and len(df) > 0:
            return float(df["Close"].values[-1])
    except Exception as e:
        logger.error(f"yfinance spot hatası: {e}")
    return None


def get_silver_data(interval: str = "1h", period: str = "60d"):
    df = _indir(TICKER_XAG, period, interval)
    if df is None:
        raise ValueError(f"Gümüş verisi alınamadı ({interval})")
    return df


def get_gold_data(interval: str = "1h", period: str = "60d"):
    df = _indir(TICKER_XAU, period, interval)
    if df is None:
        raise ValueError(f"Altın verisi alınamadı ({interval})")
    return df


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
            logger.info(
                f"Gümüş fiyatı: alış={alis}, satış={satis}, makas={makas}"
            )
            return alis, satis, makas
        logger.error("Gümüş fiyatı regex eşleşmedi - HTML yapısı değişmiş olabilir")
        return None, None, None
    except Exception as e:
        logger.error(f"Dünya Katılım scraping hatası: {e}")
        a, s = _fiyat_cache.get("alis"), _fiyat_cache.get("satis")
        if a is not None and s is not None:
            return a, s, _dunya_makas(a, s)
        return None, None, None


def get_usdtry() -> Optional[float]:
    global _USDTRY_CACHE
    now = time.time()
    t0 = float(_USDTRY_CACHE.get("ts") or 0.0)
    if t0 and (now - t0) < _USDTRY_TTL and _USDTRY_CACHE.get("data"):
        return _USDTRY_CACHE["data"]
    c = _get_td_client()
    if not c:
        _USDTRY_CACHE = {"data": None, "ts": now}
        return None
    val: Optional[float] = None
    try:
        df = _td_ohlcv("USDTRY=X", "1d", 5, order="asc")
        if df is not None and len(df) > 0 and "Close" in df.columns:
            val = float(df["Close"].values[-1])
    except Exception as e:
        logger.error("USD/TRY fiyat hatası: %s", e)
    _USDTRY_CACHE = {"data": val, "ts": now}
    return val


def get_silver_price_tl():
    """
    Sapma filtresi: SI son USD/oz (Twelve Data) ve USD/TRY → TL/gram
    (Dünya Katılım fiyatıyla karşılaştırmak için aynı birim).
    """
    try:
        spot = get_xagusd_spot_last()
        usd_try = get_usdtry()
        if spot is None or usd_try is None:
            return None, None
        try_per_gram = (float(spot) / 31.1035) * float(usd_try)
        return float(try_per_gram), float(usd_try)
    except Exception as e:
        logger.error(f"TL fiyat hatası (gümüş): {e}")
        return None, None


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
            logger.info(
                f"Altın fiyatı: alış={alis}, satış={satis}, makas={makas}"
            )
            return alis, satis, makas
        logger.error("Altın fiyatı regex eşleşmedi - HTML yapısı değişmiş olabilir")
        return None, None, None
    except Exception as e:
        logger.error(f"Dünya Katılım altın scraping hatası: {e}")
        a, s = _altin_cache.get("alis"), _altin_cache.get("satis")
        if a is not None and s is not None:
            return a, s, _dunya_makas(a, s)
        return None, None, None


def get_gold_price_tl():
    try:
        xau = _td_ohlcv(TICKER_XAU, "5m", 50, order="asc")
        usd_try = get_usdtry()
        if xau is None or usd_try is None or len(xau) < 1:
            return None, None
        xau_usd = float(xau["Close"].values[-1])
        u = float(usd_try)
        xau_tl_gram = (xau_usd / 31.1035) * u
        return xau_tl_gram, u
    except Exception as e:
        logger.error(f"Altın TL fiyat hatası: {e}")
        return None, None


def get_market_context() -> Dict[str, Any]:
    """
    Piyasa özeti: Twelve Data günlük seri (2 kapanış) — değişim / % değişim.
    DXY bu fonksiyonda çekilmez; sinyal motoru dxy_degisim_yuzde yok sayar (0).
    Sonuç 5 dk boyunca in-memory cache'ten servis edilir.
    """
    global _MARKET_CONTEXT_CACHE
    now = time.time()
    t0 = float(_MARKET_CONTEXT_CACHE.get("ts") or 0.0)
    if t0 and (now - t0) < _MARKET_CONTEXT_TTL:
        return _MARKET_CONTEXT_CACHE["data"]  # type: ignore[return-value]
    ctx: Dict[str, Any] = {}
    semboller = {
        "gumus": (TICKER_XAG, "5d", "1d"),  # SI=F
    }
    for anahtar, (ticker, period, interval) in semboller.items():
        try:
            df = _indir(ticker, period, interval)
            if df is not None and len(df) >= 2 and "Close" in df:
                vals = df["Close"].astype(float).values
                c1, c0 = float(vals[-1]), float(vals[-2])
                ctx[anahtar] = c1
                ctx[f"{anahtar}_degisim"] = c1 - c0
                ctx[f"{anahtar}_degisim_yuzde"] = (
                    (c1 - c0) / c0 * 100 if c0 else 0.0
                )
            else:
                ctx[anahtar] = None
        except Exception as e:
            logger.error(f"{anahtar} context hatası: {e}")
            ctx[anahtar] = None
    _MARKET_CONTEXT_CACHE = {"data": ctx, "ts": now}
    return ctx


def get_cot_data():
    try:
        url = "https://www.cftc.gov/dea/newcot/f_disagg.txt"
        response = requests.get(url, timeout=15)
        lines = response.text.strip().split("\n")
        for line in lines:
            if "SILVER" in line.upper():
                parts = line.split(",")
                try:
                    report_date = parts[2].strip().strip('"')
                    comm_long = float(parts[7].strip())
                    comm_short = float(parts[8].strip())
                    noncomm_long = float(parts[13].strip())
                    noncomm_short = float(parts[14].strip())
                    open_interest = float(parts[3].strip())
                    total = comm_long + comm_short
                    short_ratio = (comm_short / total) * 100 if total > 0 else 50
                    net_spekulatif = noncomm_long - noncomm_short
                    return {
                        "short_ratio": short_ratio,
                        "comm_long": comm_long,
                        "comm_short": comm_short,
                        "net_spekulatif": net_spekulatif,
                        "open_interest": open_interest,
                        "tarih": report_date,
                    }
                except Exception as e:
                    logger.error(f"COT satır ayrıştırma: {e}")
        return {
            "short_ratio": 50,
            "net_spekulatif": 0,
            "open_interest": 0,
            "tarih": "bilinmiyor",
        }
    except Exception as e:
        logger.error(f"COT hatası: {e}")
        return {
            "short_ratio": 50,
            "net_spekulatif": 0,
            "open_interest": 0,
            "tarih": "bilinmiyor",
        }


def get_macro_data():
    return {
        "cpi": 3.0,
        "fed_rate": 4.5,
        "ism": 50.0,
    }


def get_gsr():
    try:
        xau = _td_ohlcv("GC=F", "1d", 120, order="asc")
        xag = _td_ohlcv("SI=F", "1d", 120, order="asc")
        if xau is None or xag is None or len(xau) < 2 or len(xag) < 2:
            return None, None, None
        a = xau["Close"].astype(float)
        b = xag["Close"].astype(float)
        common = a.index.intersection(b.index)
        if len(common) < 2:
            n = min(len(a), len(b))
            gsr_seri = pd.Series(a.values[-n:] / b.values[-n:], dtype=float)
        else:
            gsr_seri = a.loc[common] / b.loc[common]
        gsr_guncel = float(gsr_seri.iloc[-1])
        gsr_ort = float(gsr_seri.mean())
        gsr_std = float(gsr_seri.std())
        zscore = (gsr_guncel - gsr_ort) / gsr_std if gsr_std > 0 else 0
        return gsr_guncel, gsr_ort, zscore
    except Exception as e:
        logger.error(f"GSR hatası: {e}")
        return None, None, None
