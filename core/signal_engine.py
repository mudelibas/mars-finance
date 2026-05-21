# --- Gümüş: Sweep + Reclaim sinyal motoru ---
# Sadece LONG (AL) sinyali
# Yapısal hedef: sweep öncesi 20 mumun en yüksek seviyesi
# Minimum kar filtresi: %1.25
# 15 dakika bekleme: ard arda sinyal önlenir
from datetime import datetime, timezone, timedelta
TR = timezone(timedelta(hours=3))

import logging
from typing import Any, Dict, Optional, Tuple

from core.position_store import state_oku, state_yaz

import pandas as pd

from core.data_engine import (
    get_silver_mtf,
    get_silver_price_dunyakatilim,
)

logger = logging.getLogger(__name__)

SEVIYE_PENCERE = 20
MIN_KAR_CARPAN = 1.0125

_son_sinyal_giris: float | None = None
_son_sinyal_mum_ts: Any | None = None


def _tahmini_sure(net_kar: float) -> int:
    if net_kar < 2:
        return 26
    elif net_kar < 3:
        return 31
    elif net_kar < 4:
        return 41
    else:
        return 47


def _sweep_reclaim(o15: pd.DataFrame) -> Tuple[bool, Optional[str], Optional[float], Optional[float]]:
    if o15 is None or len(o15) < SEVIYE_PENCERE + 2:
        return False, None, None, None

    pencere     = o15.iloc[-(SEVIYE_PENCERE + 2) : -2]
    sweep_mum   = o15.iloc[-2]
    reclaim_mum = o15.iloc[-1]

    onceki_yuksek = float(pencere["High"].max())
    onceki_dusuk  = float(pencere["Low"].min())

    sweep_low   = float(sweep_mum["Low"])
    sweep_close = float(sweep_mum["Close"])

    reclaim_close = float(reclaim_mum["Close"])
    reclaim_open  = float(reclaim_mum["Open"])

    # Sadece LONG
    if (sweep_low < onceki_dusuk and
            sweep_close > onceki_dusuk and
            reclaim_close > reclaim_open):
        giris = reclaim_close
        tp_usd = onceki_yuksek
        if giris <= 0:
            return False, None, None, None
        hedef_yuzde = tp_usd / giris
        return True, "long", giris, hedef_yuzde

    return False, None, None, None


def degerlendir(
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    global _son_sinyal_giris, _son_sinyal_mum_ts
    del config

    nmk: Dict[str, Any] = {
        "sinyal": False,
        "yon": None,
        "giris_tl": 0.0,
        "hedef_tl": 0.0,
        "net_kar_yuzde": 0.0,
        "tahmini_sure_saat": 0,
        "skor": 100,
        "red_neden": None,
    }

    # Fiyat verisi
    al, st, mks = get_silver_price_dunyakatilim()
    if al is None or st is None:
        nmk["red_neden"] = "Dünya Katılım fiyat alınamadı"
        return nmk

    # Mum verisi
    mtf = get_silver_mtf()
    o15 = (mtf or {}).get("15m")
    if o15 is None or len(o15) < SEVIYE_PENCERE + 2:
        nmk["red_neden"] = "15m verisi yetersiz"
        return nmk

    # Sweep + Reclaim
    sinyal, yon, giris_usd, hedef_yuzde = _sweep_reclaim(o15)
    if not sinyal:
        nmk["red_neden"] = "Sweep+Reclaim yok"
        return nmk

    # Minimum kar filtresi
    if hedef_yuzde < MIN_KAR_CARPAN:
        nmk["red_neden"] = f"Yapısal hedef yetersiz (%{(hedef_yuzde-1)*100:.2f} < %1.25)"
        return nmk

    # Dünya Katılım fiyatına uygula
    giris_tl = float(st)
    hedef_tl = round(giris_tl * hedef_yuzde, 4)
    net_kar  = (hedef_yuzde - 1.0) * 100.0
    sure     = _tahmini_sure(net_kar)

    nmk["sinyal"]            = True
    nmk["yon"]               = "long"
    nmk["giris_tl"]          = round(giris_tl, 4)
    nmk["hedef_tl"]          = round(hedef_tl, 4)
    nmk["net_kar_yuzde"]     = round(net_kar, 2)
    nmk["tahmini_sure_saat"] = sure
    nmk["red_neden"]         = None

    from datetime import datetime as _dt
    son_giris_str = state_oku("son_sinyal_giris")
    son_zaman_str = state_oku("son_sinyal_zaman")

    if son_giris_str and son_zaman_str:
        try:
            son_giris = float(son_giris_str)
            son_zaman = _dt.strptime(son_zaman_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TR)
            fark_dk = (datetime.now(TR) - son_zaman).total_seconds() / 60
            if fark_dk < 15:
                if giris_tl >= son_giris or (son_giris - giris_tl) < 0.50:
                    state_yaz("son_sinyal_giris", str(giris_tl))
                    nmk["sinyal"] = False
                    nmk["red_neden"] = "Aynı mumda daha iyi fiyat bekleniyor"
                    return nmk
        except Exception:
            pass

    state_yaz("son_sinyal_giris", str(giris_tl))
    state_yaz("son_sinyal_zaman", datetime.now(TR).strftime("%Y-%m-%d %H:%M:%S"))

    return nmk


sinyal_uret = degerlendir


def tam_analiz_calistir(
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return degerlendir(config)