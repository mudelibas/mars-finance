import json
import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.data_engine import (
    get_market_context,
    get_silver_price_dunyakatilim,
    get_gold_price_dunyakatilim,
    get_xagusd_spot_last,
)
from core.signal_engine import sinyal_uret
from core import position_store as pstore
from modules.news import haber_listesi
import config as cfg

logger = logging.getLogger(__name__)
app = Flask(__name__, static_folder="dashboard")
CORS(app)

TR = timezone(timedelta(hours=3))
LOG_DOSYA = "sinyal_log.json"
_cache = {"veri": None, "zaman": 0.0}
CACHE_SURE = 60

PERFORMANS_DOSYA = "performans.json"


def _sinyal_log_oku() -> List[Any]:
    if not os.path.exists(LOG_DOSYA):
        return []
    with open(LOG_DOSYA, encoding="utf-8") as f:
        return json.load(f)


def _performans_oku() -> Dict[str, Any]:
    if not os.path.exists(PERFORMANS_DOSYA):
        return {}
    with open(PERFORMANS_DOSYA, encoding="utf-8") as f:
        return json.load(f)


def _son_sinyal_kayit(log: List[Any]) -> Optional[Dict[str, Any]]:
    for r in reversed(log):
        if r.get("tip") == "ALIM":
            return {
                "giris_tl": r.get("giris_tl"),
                "hedef_tl": r.get("hedef_tl"),
                "net_kar_yuzde": r.get("net_kar_yuzde"),
                "skor": r.get("skor", r.get("kurul_gorusu")),
                "tarih": r.get("tarih") or r.get("giris_tarihi"),
                "signal_id": r.get("signal_id"),
            }
    return None


def _config_dict() -> dict:
    return {
        k: getattr(cfg, k)
        for k in dir(cfg)
        if not k.startswith("_")
        and isinstance(getattr(cfg, k), (int, float, str, list, dict))
    }


@app.route("/api/durum")
def durum():
    try:
        t0 = time.time()
        if _cache["veri"] is not None and (t0 - _cache["zaman"] < CACHE_SURE):
            return jsonify(_cache["veri"])

        gumus_alis, gumus_satis, gumus_makas = get_silver_price_dunyakatilim()
        altin_alis, altin_satis, _ = get_gold_price_dunyakatilim()
        xag_usd = get_xagusd_spot_last()
        pctx = get_market_context() or {}
        gumus_degisim = pctx.get("gumus_degisim_yuzde") or 0

        log = _sinyal_log_oku()
        son_sinyal = _son_sinyal_kayit(log)

        ev = sinyal_uret(_config_dict())
        veto = None if ev.get("sinyal") else (ev.get("red_neden") or None)

        st = pstore.istatistik_ozet()
        pf = _performans_oku()
        toplam_isl = int(pf.get("islem", 0) or 0)
        if toplam_isl < int(st.get("closed_count") or 0):
            toplam_isl = int(st.get("closed_count") or 0)

        open_sig = pstore.tüm_acikler()
        ledger = pstore.tüm_kayitlar()[-50:]
        log_tail = list(reversed(log))[:20] if log else []

        veri = {
            "gumus_alis": gumus_alis,
            "gumus_satis": gumus_satis,
            "gumus_makas": gumus_makas,
            "altin_alis": altin_alis,
            "altin_satis": altin_satis,
            "son_sinyal": son_sinyal,
            "sinyal_log": log_tail,
            "open_signals": open_sig,
            "signal_ledger": ledger,
            "stats": {
                "kazanma_orani_yuzde": st.get("success_rate_pct"),
                "toplam_islem_sayisi": toplam_isl,
                "kapanan_sinyal": st.get("closed_count", 0),
                "kazanan_kapanis": st.get("wins", 0),
                "aktif_sinyal": st.get("active_count", 0),
                "open_older_24h": st.get("open_older_24h", 0),
            },
            "haberler": haber_listesi()[:10],
            "veto_neden": veto,
            "guncelleme": datetime.now(TR).replace(microsecond=0).isoformat(),
            "gumus_usd": xag_usd,
            "gumus_degisim": gumus_degisim,
            "piyasa_gostergeler": pctx,
        }
        _cache["veri"] = veri
        _cache["zaman"] = time.time()
        return jsonify(veri)
    except Exception as e:
        logger.error("API hatası: %s", e, exc_info=True)
        return jsonify({"hata": str(e)}), 500


@app.route("/")
def index():
    return send_from_directory("dashboard", "index.html")


def flask_baslat():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
