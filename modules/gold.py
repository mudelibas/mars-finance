# --- XAU onayı: 5m’de gümüşle aynı yönde (yükseliş) hizalama ---

import logging
from core.data_engine import get_silver_mtf, get_xau_5m
import config as cfg

logger = logging.getLogger(__name__)


def calistir(config):
    """
    XAG ve XAU 5m: EMA20 üzeri kapanış = yükseliş; ikisi aynı anda lisans.
    Ters: XAG sinyali reddedilir (voting’de düşük puan).
    """
    try:
        mtf = get_silver_mtf()
        x5 = mtf.get("5m") if mtf else None
        g5 = get_xau_5m()
        if x5 is None or g5 is None or len(x5) < 30 or len(g5) < 30:
            logger.info("[GOLD] 5m veri eksik → uyum= False")
            return {
                "modul": "gold",
                "puan": 0.0,
                "xag_xau_uyum": False,
                "detay": {"durum": "5m yetersiz"},
            }

        span = int(config.get("EMA_TREND_HIZLI", 20))
        c_x = x5["Close"].astype(float)
        c_g = g5["Close"].astype(float)
        ex = c_x.ewm(span=span, adjust=False, min_periods=span).mean()
        eg = c_g.ewm(span=span, adjust=False, min_periods=span).mean()
        lx, exv = float(c_x.values[-1]), float(ex.values[-1])
        lg, egv = float(c_g.values[-1]), float(eg.values[-1])

        # Her iki emtia "bull" aynı anda
        up_x, up_g = lx > exv, lg > egv
        uyum = bool(up_x and up_g)
        puan = 85.0 if uyum else 15.0
        if uyum and lx > 1.01 * exv and lg > 1.01 * egv:
            puan = min(100, puan + 10.0)

        logger.info(
            f"[GOLD] uyum={uyum} xag(ema)={lx/exv:.4f} xau(ema)={lg/egv:.4f} puan={puan}"
        )
        return {
            "modul": "gold",
            "puan": round(puan, 1),
            "xag_xau_uyum": uyum,
            "detay": {
                "xag_5m_ema20": f"{exv:.4f}",
                "xau_5m_ema20": f"{egv:.4f}",
            },
        }
    except Exception as e:
        logger.error(f"[GOLD] modül: {e}")
        return {
            "modul": "gold",
            "puan": 0.0,
            "xag_xau_uyum": False,
            "detay": {"hata": str(e)},
        }
