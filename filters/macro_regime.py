import logging
from core.data_engine import get_macro_data, get_market_context

logger = logging.getLogger(__name__)

# Rejim sabitleri
REJIMLER = {
    "risk_on":       "Risk-On",
    "risk_off":      "Risk-Off",
    "enflasyonist":  "Enflasyonist",
    "deflasyonist":  "Deflasyonist",
}

def belirle(config):
    try:
        ctx  = get_market_context()
        macro = get_macro_data()

        vix     = ctx.get("vix") or 20
        dxy     = ctx.get("dxy_degisim_yuzde") or 0
        sp500   = ctx.get("sp500_degisim_yuzde") or 0
        faiz    = ctx.get("faiz") or 4.5
        fed_rate = macro.get("fed_rate") or 4.5
        cpi     = macro.get("cpi") or 3.0

        # Rejim belirleme mantığı
        if vix > 30 or sp500 < -2:
            rejim = "risk_off"
        elif cpi and cpi > 4.0 and faiz < cpi:
            rejim = "enflasyonist"
        elif faiz > 5.0 and sp500 < 0:
            rejim = "deflasyonist"
        else:
            rejim = "risk_on"

        # Gümüş için rejim skoru
        # Enflasyonist ve risk-off gümüşe en iyi ortam
        rejim_puan = {
            "enflasyonist": 75,
            "risk_off":     70,
            "risk_on":      55,
            "deflasyonist": 30,
        }

        puan = rejim_puan.get(rejim, 50)

        logger.info(f"Makro rejim: {rejim} ({puan})")

        return {
            "modul": "makro",
            "rejim": rejim,
            "rejim_str": REJIMLER[rejim],
            "puan": puan,
            "vix": vix,
            "faiz": faiz,
            "detay": {
                "rejim": f"Makro rejim: {REJIMLER[rejim]}",
                "faiz": f"ABD 10Y Faiz: %{faiz:.2f}",
                "fed": f"Fed Fonu: %{fed_rate:.2f}" if fed_rate else "Fed verisi yok",
            }
        }

    except Exception as e:
        logger.error(f"Makro rejim hatası: {e}")
        return {
            "modul": "makro",
            "rejim": "risk_on",
            "rejim_str": "Bilinmiyor",
            "puan": 50,
            "detay": {"hata": str(e)},
        }
