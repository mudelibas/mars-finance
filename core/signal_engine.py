# --- Gümüş: sapma, sweep, skor (0–100), ATR/TL hedef, setup iptal ---
# voting_engine, LLM, kurul yok.

import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

import config as cfg0
from config import (
    ATR_CARPAN_TP_GUCLU,
    ATR_CARPAN_TP_ZAYIF,
    EMA_TREND_HIZLI,
    EMA_TREND_YAVAS,
)
from core.data_engine import (
    get_market_context,
    get_silver_mtf,
    get_silver_price_dunyakatilim,
    get_silver_price_tl,
    get_usdtry,
)

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SETUP_STATE_DOSYA = os.path.join(_ROOT, "signal_setup_state.json")


def _state_yukle() -> Dict[str, Any]:
    if not os.path.exists(_SETUP_STATE_DOSYA):
        return {}
    try:
        with open(_SETUP_STATE_DOSYA, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _state_kaydet(d: Dict[str, Any]) -> None:
    try:
        with open(_SETUP_STATE_DOSYA, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("signal state yazılamadı: %s", e)


# ——— OHLC ———

def _true_range(h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    pc = c.shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def _atr14_df(df: pd.DataFrame) -> float:
    if df is None or len(df) < 16 or not all(
        c in df.columns for c in ("High", "Low", "Close")
    ):
        return 0.0
    h = df["High"].astype(float)
    l_ = df["Low"].astype(float)
    c = df["Close"].astype(float)
    tr = _true_range(h, l_, c)
    a = tr.ewm(alpha=1.0 / 14, adjust=False).mean()
    return float(a.values[-1])


def _adx14_atr14(df: pd.DataFrame) -> Tuple[float, float]:
    if df is None or len(df) < 20:
        return 20.0, 0.0
    h = df["High"].astype(float)
    l_ = df["Low"].astype(float)
    c = df["Close"].astype(float)
    n = 14
    up = h.diff()
    do = -l_.diff()
    plus_dm = ((up > do) & (up > 0)) * up
    minus_dm = ((do > up) & (do > 0)) * do
    tr = _true_range(h, l_, c)
    atr = tr.ewm(alpha=1.0 / n, adjust=False).mean()
    pdi = 100.0 * (plus_dm.ewm(alpha=1.0 / n, adjust=False).mean() / atr)
    mdi = 100.0 * (minus_dm.ewm(alpha=1.0 / n, adjust=False).mean() / atr)
    s = pdi + mdi
    dx = 100.0 * (pdi - mdi).abs() / s.replace(0, np.nan)
    adx = dx.ewm(alpha=1.0 / n, adjust=False).mean()
    return float(np.nan_to_num(adx.values[-1], nan=20.0)), float(atr.values[-1])


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _vwap(df: pd.DataFrame) -> pd.Series:
    h, l, c = (
        df["High"].astype(float),
        df["Low"].astype(float),
        df["Close"].astype(float),
    )
    if "Volume" in df.columns:
        v = df["Volume"].astype(float).clip(0, None)
    else:
        v = pd.Series(1.0, index=df.index)
    tp = (h + l + c) / 3.0
    g = (df.index.normalize() if df.index.tz is None
         else df.index.tz_convert("UTC").normalize())
    cump = (tp * v).groupby(g).cumsum()
    cumv = v.groupby(g).cumsum().replace(0, np.nan)
    return cump / cumv


def _hh_hl_15m(df: pd.DataFrame) -> bool:
    if df is None or len(df) < 12:
        return True
    lo = df["Low"].astype(float)
    c_ = df["Close"].astype(float)
    lo_m = lo.rolling(3, center=True).min()
    dps = []
    for i in range(2, len(lo) - 2):
        if (
            lo_m.iloc[i] == lo.iloc[i]
            and lo.iloc[i] < lo.iloc[i - 1]
            and lo.iloc[i] < lo.iloc[i + 1]
        ):
            dps.append(i)
    if len(dps) < 2:
        return float(c_.values[-1]) > float(c_.values[-4])
    return float(lo.values[dps[-1]]) > float(lo.values[dps[-2]])


# ——— Sapma ———

def _sapma_filtresi(
    f_ty: Optional[float], f_dk: Optional[float], adx: float, c: Any
) -> Tuple[bool, Optional[str]]:
    if f_ty is None or f_dk is None or f_dk <= 0:
        return False, "Fiyat (sapma referans) alınamadı"
    baz = float(getattr(c, "SAPMA_BAZ_YDE", 0.3) or 0.3)
    eşik = baz * (1.0 + max(0.0, (adx - 20.0)) / 100.0)
    fark_yz = abs(f_ty - f_dk) / f_dk * 100.0
    if fark_yz > eşik:
        return False, "Fiyat sapması"
    return True, None


# ——— Sweep: son 5x1m içinde fitil+toparlanma; tam df’de mum sayısı ———

def _sweep_bekle_suresi_hesap(adx: float) -> int:
    w = 3.0 + min(3.0, max(0.0, (min(adx, 50) - 15) / 35) * 3.0)
    w = int(round(w))
    return max(3, min(6, w))


def _mum_sweep_satiri(o: float, c: float, h_: float, l_: float) -> bool:
    r0 = h_ - l_
    if r0 < 1e-8:
        return False
    govde = abs(c - o)
    lo_f = min(o, c) - l_
    if not (lo_f > 2.0 * govde and r0 > 1e-6):
        return False
    return (c - l_) / r0 >= 0.3


def _o1_sweep_engel_mesajı(o1: pd.DataFrame, adx: float) -> Optional[str]:
    if o1 is None or len(o1) < 5:
        return None
    w = _sweep_bekle_suresi_hesap(adx)
    t5 = o1.tail(5)
    for ix in t5.index:
        r = t5.loc[ix]
        if not _mum_sweep_satiri(
            float(r["Open"]), float(r["Close"]),
            float(r["High"]), float(r["Low"]),
        ):
            continue
        j = o1.index.get_loc(ix)
        if isinstance(j, (slice, np.ndarray)):
            if isinstance(j, np.ndarray) and j.size:
                j0 = int(j.flat[-1])
            else:
                continue
        else:
            try:
                j0 = int(j)
            except (TypeError, ValueError):
                continue
        n_after = (len(o1) - 1) - j0
        if n_after < w:
            return "Sweep (bekleme)"
    return None


# ——— Skorlar ———

def _skor_trend_mom(o5: pd.DataFrame, o15: pd.DataFrame) -> float:
    if o15 is None or len(o15) < 50 or o5 is None or len(o5) < 30:
        return 0.0
    c15 = o15["Close"].astype(float)
    e2 = _ema(c15, EMA_TREND_HIZLI)
    e5 = _ema(c15, EMA_TREND_YAVAS)
    p1 = 0.0
    if float(e2.values[-1]) > float(e5.values[-1]):
        p1 += 35.0
    if _hh_hl_15m(o15):
        p1 += 30.0
    c5 = o5["Close"].astype(float)
    h5 = o5["High"].astype(float)
    e25 = _ema(c5, EMA_TREND_HIZLI)
    p2 = 0.0
    if float(c5.values[-1]) > float(e25.values[-1]) * 0.998:
        p2 += 20.0
    k = min(8, len(h5) - 1)
    son_max = float(h5.values[-1])
    o_max = float(h5.values[-(k + 1) : -1].max())
    if son_max >= o_max * 0.9985:
        p2 += 15.0
    return min(100.0, p1 + p2)


def _skor_volatilite(
    adx: float, atr: float, close: float, ctx: Optional[Dict], cfg: Any
) -> float:
    s = 40.0 + min(45.0, (adx - 10.0) * 0.7)
    s = float(np.clip(s, 5.0, 95.0))
    if close and atr / close > 0.04:
        s = max(5.0, s - 25.0)
    dxy_roc = 0.0
    if ctx and ctx.get("dxy_degisim_yuzde") is not None:
        try:
            dxy_roc = float(ctx.get("dxy_degisim_yuzde") or 0.0)
        except (TypeError, ValueError):
            dxy_roc = 0.0
    esk = float(getattr(cfg, "MAKRO_DXY_ANI_ESIK", 0.5))
    if abs(dxy_roc) > esk:
        s = max(5.0, s - 20.0)
    return min(100.0, s)


def _skor_giris(o1: pd.DataFrame) -> float:
    if o1 is None or len(o1) < 40:
        return 0.0
    c1 = o1["Close"].astype(float)
    h1 = o1["High"].astype(float)
    e1 = _ema(c1, EMA_TREND_HIZLI)
    vw = _vwap(o1)
    s = 0.0
    ce, ve = float(c1.values[-1]), float(vw.values[-1])
    band = 0.0022 * max(ce, 1.0)
    if abs(ce - e1.values[-1]) < band * 2 or abs(ce - ve) < band * 2:
        s += 50.0
    look = min(35, len(h1) - 1)
    res = float(h1.values[-(look + 1) :].max()) if look > 0 else float(h1.values[-1])
    if (res - ce) / res > 0.0025:
        s += 50.0
    else:
        s += 15.0
    return min(100.0, s)


def _bilesik_skor(
    a: float, b: float, c: float
) -> int:
    return int(
        min(100, max(0, 0.38 * a + 0.32 * b + 0.30 * c))
    )


# ——— Setup iptal: önceki sinyal sonrası fiyat, ATR/2 tersi ———

def _setup_iptal_fiyat(
    giris: float, atr_half: float, orta: Optional[float]
) -> bool:
    if orta is None or giris is None or atr_half is None or atr_half <= 0:
        return False
    return float(orta) < float(giris) - float(atr_half)


def degerlendir(
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    del config
    cfg = cfg0
    nmk: Dict[str, Any] = {
        "sinyal": False,
        "giris_tl": 0.0,
        "hedef_tl": 0.0,
        "net_kar_yuzde": 0.0,
        "skor": 0,
        "red_neden": None,
    }
    f_ty, _usd = get_silver_price_tl()
    al, st, mks = get_silver_price_dunyakatilim()
    f_dk: Optional[float] = None
    dmy: float = 0.0
    if al is not None and st is not None:
        f_dk = (float(al) + float(st)) / 2.0
        dmy = float(f_dk)

    mtf = get_silver_mtf()
    o1 = (mtf or {}).get("1m")
    o5 = (mtf or {}).get("5m")
    o15 = (mtf or {}).get("15m")
    if o15 is None or len(o15) < 50 or o5 is None or len(o5) < 30:
        nmk["red_neden"] = "Mum verisi yetersiz"
        return nmk
    if o1 is None or len(o1) < 30:
        nmk["red_neden"] = "1m verisi yetersiz"
        return nmk

    adx, _atr15_usd = _adx14_atr14(o15)
    atr15_usd = _atr14_df(o15) if _atr15_usd <= 0 else _atr15_usd
    c15 = float(o15["Close"].astype(float).values[-1])
    stt = _state_yukle()
    prev = (stt or {}).get("son_sinyal") or {}
    if prev.get("gecersiz"):
        pass
    usdtr = get_usdtry() or 0.0
    if usdtr <= 0 and f_ty and c15:
        t = c15 / 31.1035
        if t and t > 0:
            usdtr = float(f_ty) / t
    if usdtr <= 0:
        nmk["red_neden"] = "USD/TRY yok"
        return nmk

    atr15_tl_gram = (float(atr15_usd) / 31.1035) * float(usdtr)

    orta = f_dk if f_dk is not None and f_dk > 0 else None
    if prev.get("giris_tl") and prev.get("atr_half_tl") and orta is not None:
        if not prev.get("gecersiz") and _setup_iptal_fiyat(
            float(prev["giris_tl"]),
            float(prev["atr_half_tl"]),
            float(orta),
        ):
            nmk["red_neden"] = "Setup iptal (ters hareket)"
            _state_kaydet(
                {**stt, "son_sinyal": {**prev, "gecersiz": True, "t": time.time()}}
            )
            return nmk

    gecerli, sdn = _sapma_filtresi(f_ty, f_dk, adx, cfg)
    if not gecerli:
        nmk["red_neden"] = sdn
        nmk["skor"] = 0
        return nmk

    swm = _o1_sweep_engel_mesajı(o1, adx)
    if swm:
        nmk["red_neden"] = swm
        return nmk

    a = _skor_trend_mom(o5, o15)
    b = _skor_volatilite(adx, float(atr15_usd or 0.0), c15, get_market_context(), cfg)
    x = _skor_giris(o1)
    skr = _bilesik_skor(a, b, x)
    nmk["skor"] = int(skr)
    th = int(getattr(cfg, "SKOR_ESIK", 65) or 65)
    if skr < th:
        nmk["red_neden"] = f"Skor eşiği ({skr}<{th})"
        return nmk

    mtp = ATR_CARPAN_TP_GUCLU if adx > 25 else ATR_CARPAN_TP_ZAYIF
    if st is not None:
        giris = float(st)
    elif dmy > 0:
        giris = dmy
    else:
        giris = 0.0
    if giris is None or giris <= 0:
        nmk["red_neden"] = "Dünya Katılım fiyat (satış) yok"
        return nmk
    h_brut = giris + (atr15_tl_gram * mtp)
    mks_tl = float(mks) if mks else 0.0
    verg = float(getattr(cfg, "VERGI_YDE", 0.2) or 0.2)
    nkm = float(getattr(cfg, "NET_KAR_MIN_YDE", 1.0) or 1.0)
    netp = 100.0 * (h_brut - giris) / giris - verg
    if mks_tl and giris > 0:
        netp -= 100.0 * 0.5 * mks_tl / giris
    if netp < nkm:
        nmk["red_neden"] = f"Net kâr < %{nkm} (tah. %{netp:.2f})"
        nmk["giris_tl"] = float(giris)
        nmk["hedef_tl"] = float(h_brut)
        nmk["net_kar_yuzde"] = float(netp)
        return nmk

    aht = 0.5 * float(atr15_tl_gram)
    nmk["sinyal"] = True
    nmk["giris_tl"] = float(giris)
    nmk["hedef_tl"] = float(h_brut)
    nmk["net_kar_yuzde"] = float(netp)
    nmk["atr_half_tl"] = aht
    nmk["red_neden"] = None
    yeni = {**_state_yukle(), "son_sinyal": {
        "giris_tl": nmk["giris_tl"],
        "atr_half_tl": aht,
        "t": time.time(),
        "gecersiz": False,
    }}
    _state_kaydet(yeni)
    return nmk


# ——— dış açılış ———

sinyal_uret = degerlendir


def tam_analiz_calistir(
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return degerlendir(config)


def build_kapanis_mesaji_usd(
    giris_usd: float, hedef_usd: float, cikis_usd: float, _config: Any
) -> Tuple[str, float]:
    """Açık USD sinyal takibi (position_store) — kapanış (TP) metni + brüt %."""
    if not cikis_usd or not giris_usd or float(cikis_usd) < float(giris_usd):
        return "Kapanış: spot girişin altında (profit-only).", 0.0
    net_brut = (
        (float(cikis_usd) - float(giris_usd)) / float(giris_usd) * 100.0
        if giris_usd
        else 0.0
    )
    return (
        (
            f"XAG/USD kapanış (TP)\n"
            f"Giriş: ${float(giris_usd):.4f}\n"
            f"TP hedef: ${float(hedef_usd):.4f}\n"
            f"Çıkış: ${float(cikis_usd):.4f}  (brüt % {net_brut:+.2f})\n"
        ),
        float(net_brut),
    )


def build_hedef_mesaji(
    _giris_tarihi: Any, giris_tl: float, hedef_tl: float, mevcut_tl: float, _config: Any
) -> Tuple[str, float]:
    """Eski log uyumluluğu (TL)."""
    if isinstance(_config, dict):
        bsmv = float(_config.get("BSMV_KMV_YUZDE", 0.2))
    else:
        bsmv = float(getattr(_config, "BSMV_KMV_YUZDE", 0.2))
    giris_maliyeti = giris_tl * (1 + bsmv / 200) if giris_tl else 0.0
    net_c = mevcut_tl * (1 - bsmv / 200) if mevcut_tl else 0.0
    net_kar_y = (
        ((net_c - giris_maliyeti) / giris_maliyeti) * 100 if giris_maliyeti else 0.0
    )
    m = f"Gümüş\nGiriş: ₺{giris_tl:.2f}\nHedef: ₺{hedef_tl:.2f}\n"
    return m, float(net_kar_y)
