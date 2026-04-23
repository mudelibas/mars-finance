import logging
from core.data_engine import get_silver_data
from config import HACIM_ANOMALI_CARPAN

logger = logging.getLogger(__name__)

def calistir(config):
    try:
        df = get_silver_data(interval="1h", period="30d")
        if df is None or len(df) < 21:
            return {"modul": "hacim", "puan": 50, "detay": {}}
        
        hacimler = df["Volume"].values
        son_hacim = float(hacimler[-1])
        ort_hacim = float(hacimler[-21:-1].mean())
        
        if ort_hacim == 0:
            return {"modul": "hacim", "puan": 50, "detay": {}}
        
        oran = son_hacim / ort_hacim
        anomali_var = oran >= HACIM_ANOMALI_CARPAN
        
        # Yüksek hacim + fiyat yükseliyorsa iyi sinyal
        fiyatlar = df["Close"].values
        fiyat_yonu = fiyatlar[-1] > fiyatlar[-2]
        
        if anomali_var and fiyat_yonu:
            puan = 80
        elif anomali_var and not fiyat_yonu:
            puan = 20
        elif oran > 1.5 and fiyat_yonu:
            puan = 65
        elif oran < 0.5:
            puan = 45
        else:
            puan = 50
        
        return {
            "modul": "hacim",
            "puan": puan,
            "anomali": anomali_var,
            "oran": round(oran, 2),
            "detay": {"hacim_orani": oran, "anomali": anomali_var}
        }
    except Exception as e:
        logger.error(f"Hacim modülü hatası: {e}")
        return {"modul": "hacim", "puan": 50, "detay": {}}
