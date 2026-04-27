# --- Gümüş: Sweep + Reclaim sinyal motoru ---
# Yapısal hedef: sweep öncesi 20 mumun en yüksek/düşük seviyesi
# Minimum kar filtresi: yapısal hedef %1.25 kar getirmiyorsa sinyal yok
# Hedef TL: SI=F yapısal hedef yüzdesi Dünya Katılım fiyatına uygulanır

import logging
import os
import json
import time
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from core.data_engine import (
    get_silver_mtf,
    get_silver_price_dunyakatilim,
)

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SETUP_STATE_DOSYA = os.path.join(_ROOT, "signal_setup_state.json")

# ─── PARAMETRELER ───
SEVIYE_PENCERE  = 20      # kaç mumun yüksek/düşük bakılır
MIN_KAR_CARPAN  = 1.0125  # minimum %1 net kar + spread + vergi


# ─── STATE ───

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


# ─── SWEEP + RECLAIM ───

def _sweep_reclaim(o15: pd.DataFrame) -> Tuple[bool, Optional[str], Optional[float], Optional[float]]:
    """
    Son 2 mumda sweep+reclaim var mı?
    Döner: (sinyal_var, yon, giris_fiyati_usd, hedef_yuzde)
    hedef_yuzde: yapısal hedefin girişe göre yüzdesi (örn. 1.023 = %2.3 yukarı)
    """
    if o15 is None or len(o15) < SEVIYE_PENCERE + 2:
        return False, None, None, None

    pencere     = o15.iloc[-(SEVIYE_PENCERE + 2) : -2]
    sweep_mum   = o15.iloc[-2]
    reclaim_mum = o15.iloc[-1]

    onceki_yuksek = float(pencere["High"].max())
    onceki_dusuk  = float(pencere["Low"].min())

    sweep_high  = float(sweep_mum["High"])
    sweep_low   = float(sweep_mum["Low"])
    sweep_close = float(sweep_mum["Close"])

    reclaim_close = float(reclaim_mum["Close"])
    reclaim_open  = float(reclaim_mum["Open"])

    # LONG: sweep dip kırdı, close seviyenin üstünde, reclaim yeşil
    if (sweep_low < onceki_dusuk and
            sweep_close > onceki_dusuk and
            reclaim_close > reclaim_open):
        giris = reclaim_close
        tp_usd = onceki_yuksek
        if giris <= 0:
            return False, None, None, None
        hedef_yuzde = tp_usd / giris  # örn. 1.023
        return True, "long", giris, hedef_yuzde

    # SHORT: sweep zirve kırdı, close seviyenin altında, reclaim kırmızı
    if (sweep_high > onceki_yuksek and
            sweep_close < onceki_yuksek and
            reclaim_close < reclaim_open):
        giris = reclaim_close
        tp_usd = onceki_dusuk
        if giris <= 0:
            return False, None, None, None
        hedef_yuzde = tp_usd / giris  # örn. 0.977
        return True, "short", giris, hedef_yuzde

    return False, None, None, None


# ─── ANA FONKSİYON ───

def degerlendir(
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    del config

    nmk: Dict[str, Any] = {
        "sinyal": False,
        "yon": None,
        "giris_tl": 0.0,
        "hedef_tl": 0.0,
        "net_kar_yuzde": 0.0,
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

    # Sweep + Reclaim kontrolü
    sinyal, yon, giris_usd, hedef_yuzde = _sweep_reclaim(o15)
    if not sinyal:
        nmk["red_neden"] = "Sweep+Reclaim yok"
        return nmk

    # Minimum kar filtresi
    if yon == "long" and hedef_yuzde < MIN_KAR_CARPAN:
        nmk["red_neden"] = f"Yapısal hedef yetersiz (%{(hedef_yuzde-1)*100:.2f} < %1.25)"
        return nmk
    if yon == "short" and hedef_yuzde > (1 / MIN_KAR_CARPAN):
        nmk["red_neden"] = f"Yapısal hedef yetersiz (%{(1-hedef_yuzde)*100:.2f} < %1.25)"
        return nmk

    # Dünya Katılım fiyatına yüzdesel uygula
    if yon == "long":
        giris_tl = float(st)   # satış fiyatından al
        hedef_tl = round(giris_tl * hedef_yuzde, 4)
    else:
        giris_tl = float(al)   # alış fiyatından sat
        hedef_tl = round(giris_tl * hedef_yuzde, 4)

    net_kar = abs(hedef_yuzde - 1.0) * 100.0

    nmk["sinyal"]        = True
    nmk["yon"]           = yon
    nmk["giris_tl"]      = round(giris_tl, 4)
    nmk["hedef_tl"]      = round(hedef_tl, 4)
    nmk["net_kar_yuzde"] = round(net_kar, 2)
    nmk["red_neden"]     = None

    # State kaydet
    _state_kaydet({
        "son_sinyal": {
            "giris_tl":   giris_tl,
            "hedef_tl":   hedef_tl,
            "yon":        yon,
            "hedef_yuzde": hedef_yuzde,
            "t":          time.time(),
        }
    })

    return nmk


# ─── Dış erişim ───
sinyal_uret = degerlendir


def tam_analiz_calistir(
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return degerlendir(config)