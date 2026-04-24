import logging
import numpy as np
import pandas as pd
from core.data_engine import get_silver_data

logger = logging.getLogger(__name__)

def _sma(series, period):
    return series.rolling(window=period).mean()

def _atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def _garch_proxy(close):
    returns = close.pct_change().dropna()
    try:
        from arch import arch_model
        r = returns * 100
        if len(r) < 50: raise ValueError()
        model = arch_model(r, vol='Garch', p=1, q=1, dist='normal')
        res = model.fit(disp='off', show_warning=False)
        forecast = res.forecast(horizon=1)
        return float(np.sqrt(forecast.variance.values[-1][0]) / 100)
    except Exception as e:
        logger.error(f"GARCH proxy, rolling std'a düşüldü: {e}")
        return float(returns.tail(20).std())

def _zscore(seri, pencere=20):
    ort = seri.rolling(pencere).mean()
    std = seri.rolling(pencere).std()
    return (seri - ort) / std

def calistir(config):
    try:
        df = get_silver_data(interval="1d", period="365d")
        close = df["Close"].squeeze()
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()

        vol = _garch_proxy(close)
        vol_esik = config.get("VOLATILITE_YUKSEK_ESIK", 0.025)
        if vol > vol_esik:
            vol_rejim = "yuksek"; vol_puan = 20
        elif vol < vol_esik * 0.5:
            vol_rejim = "dusuk"; vol_puan = 70
        else:
            vol_rejim = "normal"; vol_puan = 55

        z = _zscore(close, 20)
        z_son = float(z.values[-1]) if not np.isnan(z.values[-1]) else 0
        if z_son < -2:
            z_puan = 85; z_yorum = f"Aşırı ucuz (Z:{z_son:.1f})"
        elif z_son < -1:
            z_puan = 70; z_yorum = f"Ortalamanın altında (Z:{z_son:.1f})"
        elif z_son > 2:
            z_puan = 15; z_yorum = f"Aşırı pahalı (Z:{z_son:.1f})"
        elif z_son > 1:
            z_puan = 35; z_yorum = f"Ortalamanın üzerinde (Z:{z_son:.1f})"
        else:
            z_puan = 55; z_yorum = f"Ortalama civarı (Z:{z_son:.1f})"

        roc_5  = float((close.values[-1] - close.values[-6])  / close.values[-6]  * 100) if len(close) > 6  else 0
        roc_20 = float((close.values[-1] - close.values[-21]) / close.values[-21] * 100) if len(close) > 21 else 0
        if roc_5 > 2 and roc_20 > 5:
            mom_puan = 75; mom_yorum = f"Güçlü momentum (5g:%{roc_5:.1f})"
        elif roc_5 > 0 and roc_20 > 0:
            mom_puan = 60; mom_yorum = f"Pozitif momentum"
        elif roc_5 < -2 and roc_20 < -5:
            mom_puan = 20; mom_yorum = f"Negatif momentum"
        else:
            mom_puan = 45; mom_yorum = f"Karışık momentum"

        atr_son = float(_atr(high, low, close).values[-1])
        toplam = (vol_puan * 0.30) + (z_puan * 0.40) + (mom_puan * 0.30)
        if vol_rejim == "yuksek": toplam = min(toplam, 55)

        return {
            "modul": "matematiksel",
            "puan": round(toplam, 1),
            "volatilite_rejim": vol_rejim,
            "volatilite_deger": round(vol * 100, 2),
            "zscore": round(z_son, 2),
            "atr": atr_son,
            "detay": {
                "volatilite": f"Volatilite: {vol_rejim} (%{vol*100:.2f})",
                "zscore": z_yorum,
                "momentum": mom_yorum,
            }
        }
    except Exception as e:
        logger.error(f"Matematiksel modül: {e}")
        return {"modul": "matematiksel", "puan": 50, "volatilite_rejim": "bilinmiyor",
                "volatilite_deger": None, "zscore": None, "atr": None, "detay": {}}
