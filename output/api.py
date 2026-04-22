import json
import os
import sys
import time
import logging
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timezone, timedelta

_cache = {"veri": None, "zaman": 0}
CACHE_SURE = 30

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.data_engine import get_silver_price_tl, get_gold_price_tl
from core.signal_engine import tam_analiz_calistir
import config as cfg

logger = logging.getLogger(__name__)
app = Flask(__name__, static_folder='dashboard')
CORS(app)

TR = timezone(timedelta(hours=3))
LOG_DOSYA    = "sinyal_log.json"
HABER_DOSYA  = "haberler_log.json"

def _sinyal_log_oku():
    if not os.path.exists(LOG_DOSYA):
        return []
    with open(LOG_DOSYA) as f:
        return json.load(f)

def _haber_log_oku():
    if not os.path.exists(HABER_DOSYA):
        return []
    with open(HABER_DOSYA) as f:
        return json.load(f)

def _haber_log_kaydet(yeni_haberler):
    mevcut = _haber_log_oku()
    mevcut_basliklar = {h["title"] for h in mevcut}
    zaman = datetime.now(TR).strftime("%H:%M")
    for h in yeni_haberler:
        if h.get("turkce", h["title"]) not in mevcut_basliklar:
            mevcut.insert(0, {
                "tier": h["tier"],
                "title": h.get("turkce", h["title"]),
                "zaman": zaman
            })
    mevcut = mevcut[:20]
    with open(HABER_DOSYA, "w") as f:
        json.dump(mevcut, f, ensure_ascii=False)

@app.route('/api/durum')
def durum():
    try:
        if _cache["veri"] is not None and (time.time() - _cache["zaman"] < CACHE_SURE):
            return jsonify(_cache["veri"])

        config_dict = {
            k: getattr(cfg, k)
            for k in dir(cfg)
            if not k.startswith('_') and isinstance(getattr(cfg, k), (int, float, str, list, dict))
        }

        sonuc = tam_analiz_calistir(config_dict)
        oylama = sonuc.get("oylama", {})
        moduller_raw = sonuc.get("modul_sonuclari", {})
        ctx = sonuc.get("ctx", {})

        gumus_tl, usd_try = get_silver_price_tl()
        altin_tl, _ = get_gold_price_tl()

        moduller = {
            k: {"puan": v.get("puan", 50)}
            for k, v in moduller_raw.items()
        }

        haber_modulu = moduller_raw.get("haberler", {})
        yeni_haberler = haber_modulu.get("detay", {}).get("haberler", [])
        if yeni_haberler:
            _haber_log_kaydet(yeni_haberler)

        veri = {
            "gumus_tl":       gumus_tl,
            "gumus_usd":      moduller_raw.get("teknik", {}).get("fiyat_usd"),
            "gumus_degisim":  ctx.get("gumus_degisim_yuzde", 0),
            "altin_tl":       altin_tl,
            "altin_usd":      ctx.get("altin"),
            "altin_degisim":  ctx.get("altin_degisim_yuzde", 0),
            "kurul_gorusu":   oylama.get("kurul_gorusu", 0),
            "rejim":          moduller_raw.get("makro", {}).get("rejim_str", "--"),
            "moduller":       moduller,
            "vix":            ctx.get("vix"),
            "dxy":            ctx.get("dxy"),
            "dxy_degisim":    ctx.get("dxy_degisim_yuzde", 0),
            "petrol":         ctx.get("petrol"),
            "petrol_degisim": ctx.get("petrol_degisim_yuzde", 0),
            "faiz":           ctx.get("faiz"),
            "sinyal_log":     list(reversed(_sinyal_log_oku()))[:10],
            "haberler":       _haber_log_oku()[:10],
            "veto":           oylama.get("veto", False),
            "veto_neden":     oylama.get("veto_neden"),
            "guncelleme":     datetime.now(TR).strftime("%H:%M"),
        }
        _cache["veri"] = veri
        _cache["zaman"] = time.time()
        return jsonify(veri)
    except Exception as e:
        logger.error(f"API hatası: {e}")
        return jsonify({"hata": str(e)}), 500

@app.route('/')
def index():
    return send_from_directory('dashboard', 'index.html')

def flask_baslat():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)