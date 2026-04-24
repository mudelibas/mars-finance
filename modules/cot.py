import logging
from core.data_engine import get_cot_data, get_silver_data

logger = logging.getLogger(__name__)

def calistir(config):
    try:
        cot = get_cot_data()
        short_ratio    = cot["short_ratio"]
        net_spekulatif = cot["net_spekulatif"]
        open_interest  = cot["open_interest"]
        cot_max        = config.get("COT_MAX_SHORT_RATIO", 65.0)

        puan = 0
        detay = {}

        # Short ratio analizi
        if short_ratio > cot_max:
            # Büyük oyuncular aşırı short = yakında kapama = fiyat yükselir
            puan += 35
            detay["short_ratio"] = (
                f"Ticari oyuncular aşırı short (%{short_ratio:.1f}) "
                f"→ Kısa vadeli dönüş sinyali"
            )
        elif short_ratio < 40:
            puan += 10
            detay["short_ratio"] = (
                f"Ticari oyuncular dengeli (%{short_ratio:.1f})"
            )
        elif short_ratio > 55:
            puan += 20
            detay["short_ratio"] = (
                f"Ticari oyuncular short ağırlıklı (%{short_ratio:.1f})"
            )
        else:
            puan += 15
            detay["short_ratio"] = f"COT nötr (%{short_ratio:.1f})"

        # Spekülatif net pozisyon
        if net_spekulatif > 30000:
            puan += 30
            detay["spekulatif"] = (
                f"Spekülatörler net long ({net_spekulatif:,.0f} kontrat)"
            )
        elif net_spekulatif > 0:
            puan += 15
            detay["spekulatif"] = (
                f"Spekülatörler hafif long ({net_spekulatif:,.0f})"
            )
        elif net_spekulatif < -30000:
            puan -= 20
            detay["spekulatif"] = (
                f"Spekülatörler net short ({net_spekulatif:,.0f}) → Dikkat"
            )
        else:
            puan += 5
            detay["spekulatif"] = f"Spekülatif pozisyon nötr"

        # Open interest değişimi (momentum)
        try:
            df_1h = get_silver_data(interval="1d", period="10d")
            vol_son  = float(df_1h["Volume"].values[-1])
            vol_ort  = float(df_1h["Volume"].mean())
            oi_degisim_puan = 0
            if vol_son > vol_ort * 1.5:
                oi_degisim_puan = 15
                detay["open_interest"] = "Hacim artışı — kurumsal ilgi artıyor"
            elif vol_son < vol_ort * 0.5:
                oi_degisim_puan = -10
                detay["open_interest"] = "Hacim düşük — kurumsal ilgi azalmış"
            else:
                detay["open_interest"] = "Hacim normal"
            puan += oi_degisim_puan
        except Exception as e:
            logger.error(f"Open interest / hacim bölümü: {e}")
            detay["open_interest"] = "Hacim verisi alınamadı"

        puan = max(0, min(100, puan))
        logger.info(f"Balina Faktörü: short={short_ratio:.1f}%, "
                    f"net_spek={net_spekulatif:.0f} → {puan}")

        return {
            "modul": "balina",
            "puan": puan,
            "short_ratio": round(short_ratio, 1),
            "net_spekulatif": net_spekulatif,
            "open_interest": open_interest,
            "cot_tarih": cot["tarih"],
            "detay": detay,
        }

    except Exception as e:
        logger.error(f"Balina Faktörü hatası: {e}")
        return {
            "modul": "balina",
            "puan": 50,
            "short_ratio": 50,
            "detay": {"hata": str(e)},
        }
