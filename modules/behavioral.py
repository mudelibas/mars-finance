import logging
import numpy as np
from core.data_engine import get_market_context, get_silver_data, get_gsr

logger = logging.getLogger(__name__)

def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calistir(config):
    try:
        ctx = get_market_context()
        vix = ctx.get("vix")
        vix_panik   = config.get("VIX_PANIK", 30)
        vix_iyimser = config.get("VIX_IYIMSER", 15)
        puan = 0
        detay = {}
        gsr = None

        if vix is not None:
            if vix > vix_panik:
                puan += 30; detay["vix"] = f"VIX {vix:.1f} — Panik, güvenli liman talebi artabilir"
            elif vix < vix_iyimser:
                puan += 10; detay["vix"] = f"VIX {vix:.1f} — Aşırı iyimserlik"
            else:
                puan += 20; detay["vix"] = f"VIX {vix:.1f} — Normal"
        else:
            puan += 15; detay["vix"] = "VIX alınamadı"

        try:
            df = get_silver_data(interval="1h", period="30d")
            close = df["Close"].squeeze()
            rsi   = _rsi(close).dropna()
            rsi_oversold   = config.get("RSI_OVERSOLD", 35)
            rsi_overbought = config.get("RSI_OVERBOUGHT", 68)
            son_20 = rsi.tail(20)
            asiri_satim = (son_20 < rsi_oversold).sum()
            asiri_alim  = (son_20 > rsi_overbought).sum()
            if asiri_satim >= 5:
                puan += 25; detay["suru"] = f"Son 20 mumun {asiri_satim}'inde aşırı satım — Dönüş beklentisi"
            elif asiri_alim >= 8:
                puan -= 20; detay["suru"] = f"Son 20 mumun {asiri_alim}'inde aşırı alım — Dikkat"
            else:
                puan += 10; detay["suru"] = "Sürü davranışı normal"
        except Exception as e:
            logger.error(f"Panikçi sürü (RSI) analizi: {e}")
            detay["suru"] = f"Sürü analizi hatası: {e}"

        try:
            gsr, gsr_ort, gsr_z = get_gsr()
            gsr_tarihi_ort = config.get("GSR_TARIHI_ORT", 65.0)
            if gsr is not None:
                if gsr > gsr_tarihi_ort * 1.2:
                    puan += 20; detay["gsr"] = f"Altın/Gümüş oranı {gsr:.1f} — Gümüş görece ucuz"
                elif gsr < gsr_tarihi_ort * 0.8:
                    puan -= 15; detay["gsr"] = f"Altın/Gümüş oranı {gsr:.1f} — Gümüş görece pahalı"
                else:
                    detay["gsr"] = f"Altın/Gümüş oranı {gsr:.1f} — Normal"
            else:
                detay["gsr"] = "GSR alınamadı"
        except Exception as e:
            logger.error(f"Panikçi GSR: {e}")
            detay["gsr"] = f"GSR hatası: {e}"
            gsr = None

        puan = max(0, min(100, puan))
        return {
            "modul": "panikci",
            "puan": puan,
            "vix": vix,
            "gsr": gsr,
            "detay": detay,
        }
    except Exception as e:
        logger.error(f"Panikçi Faktör: {e}")
        return {"modul": "panikci", "puan": 50, "vix": None, "detay": {}}
