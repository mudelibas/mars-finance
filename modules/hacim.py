# --- 5m hacim: sinyal için S spike ZORUNLU: son hacim > 20-EMA(hacim) * eşik ---

import logging
import numpy as np
import pandas as pd
from core.data_engine import get_silver_mtf
from config import HACIM_SPIKE_MIN_CARPAN

logger = logging.getLogger(__name__)


def calistir(config):
    try:
        mtf = get_silver_mtf()
        o5 = mtf.get("5m") if mtf else None
        if o5 is None or len(o5) < 30 or "Volume" not in o5.columns:
            return {
                "modul": "hacim",
                "puan": 0.0,
                "hacim_spike_ok": False,
                "detay": {"hata": "5m hacim yok"},
            }

        v = o5["Volume"].astype(float)
        v_ma = v.rolling(20, min_periods=10).mean()
        vson, vort = float(v.values[-1]), float(v_ma.values[-1])
        if vort <= 0 or np.isnan(vort):
            return {
                "modul": "hacim",
                "puan": 0.0,
                "hacim_spike_ok": False,
                "detay": {"hacim_orta": 0.0},
            }
        carpan = float(config.get("HACIM_SPIKE_MIN_CARPAN", HACIM_SPIKE_MIN_CARPAN))
        oran = vson / vort
        spike = oran >= carpan
        puan = 85.0 if spike else 5.0
        if not spike:
            logger.info(f"[HACİM] zorunlu SPIKE yok: oran={oran:.2f} < {carpan}")
        return {
            "modul": "hacim",
            "puan": round(puan, 1),
            "hacim_spike_ok": bool(spike),
            "oran": round(oran, 2),
            "detay": {"carpan_min": carpan, "hacim_oran": oran, "ZORUNLU": True},
        }
    except Exception as e:
        logger.error(f"Hacim: {e}")
        return {
            "modul": "hacim",
            "puan": 0.0,
            "hacim_spike_ok": False,
            "detay": {},
        }
