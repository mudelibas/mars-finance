import logging
from core.data_engine import get_silver_data, get_market_context

logger = logging.getLogger(__name__)

def manipulasyon_kontrol(config):
    """
    3 katmanlı manipülasyon tespiti.
    Herhangi biri tetiklenirse veto döner.
    """
    tetiklenen = []
    try:
        df = get_silver_data(interval="5m", period="1d")
        close  = df["Close"].squeeze()
        volume = df["Volume"].squeeze()

        # 1. Hacim anomalisi
        hacim_ort = volume.rolling(20).mean()
        son_hacim = float(volume.values[-1])
        ort_hacim = float(hacim_ort.values[-1])
        carpan    = config.get("HACIM_ANOMALI_CARPAN", 3.0)

        if ort_hacim > 0 and son_hacim > ort_hacim * carpan:
            tetiklenen.append(
                f"Hacim anomalisi: {son_hacim/ort_hacim:.1f}x ortalama"
            )

        # 2. Fiyat spike
        spike_esik = config.get("FIYAT_SPIKE_YUZDE", 3.0) / 100
        son_5 = close.tail(5)
        if len(son_5) >= 2:
            max_degisim = abs(
                (son_5.values[-1] - son_5.values[0]) / son_5.values[0]
            )
            if max_degisim > spike_esik:
                hacim_son_5 = volume.tail(5).mean()
                if hacim_son_5 < ort_hacim * 0.5:
                    tetiklenen.append(
                        f"Fiyat spike + düşük hacim: "
                        f"%{max_degisim*100:.1f} hareket"
                    )

    except Exception as e:
        logger.error(f"Manipülasyon kontrol hatası: {e}")

    return len(tetiklenen) > 0, tetiklenen

def hesapla_profit_target_usd(entry_oz: float, config) -> float:
    """
    Yalnız kâr hedefi (USD/oz). Stop yok.
    Net hedef: NET_TP aralığının ortası; spread + sabit gider toplamı fiyata yansıtılır.
    """
    a = (float(config.get("NET_TP_MIN_PCT", 0.75)) + float(config.get("NET_TP_MAX_PCT", 1.0))) / 2.0
    nfrac = a / 100.0
    sfrac = float(config.get("XAG_SPREAD_PCT", 0.02)) / 100.0
    cfrac = float(config.get("XAG_ORTA_MALIYET_PCT", 0.2)) / 100.0
    toplam = nfrac + sfrac + cfrac
    return round(float(entry_oz) * (1.0 + toplam), 4)


def fiyat_erkun_esigi(entry_oz: float, tp_oz: float, config) -> float:
    """%80 ilerlemede (net hedefe göre) erken uyarı seviyesi fiyat (USD/oz)."""
    f = float(config.get("ERKEN_UYARI_FRAC", 0.8))
    return float(entry_oz) + f * (float(tp_oz) - float(entry_oz))


def hesapla_stop_tp(fiyat_tl, atr_usd, usd_try, config):
    """
    Geriye dönük: SL yok, ikinci değer None.
    Aynı net brüt oranı TL fiyata uygular (1 USD/oz rasyosu ile).
    """
    if fiyat_tl is None:
        return None, None
    unit = 1.0
    katsayi = hesapla_profit_target_usd(unit, config) / unit
    return round(float(fiyat_tl) * katsayi, 2), None

def calistir(config):
    try:
        ctx = get_market_context()
        puan = 50
        detay = {}

        # Manipülasyon kontrolü (veto için ayrıca kullanılır)
        manip_var, manip_detay = manipulasyon_kontrol(config)
        if manip_var:
            puan = 10
            detay["manipulasyon"] = " | ".join(manip_detay)
        else:
            puan += 15
            detay["manipulasyon"] = "Manipülasyon sinyali yok"

        # DXY baskısı
        dxy_degisim = ctx.get("dxy_degisim_yuzde", 0) or 0
        if dxy_degisim > 0.5:
            puan -= 15
            detay["dxy"] = f"Dolar güçleniyor (%{dxy_degisim:+.2f}) — Gümüşe baskı"
        elif dxy_degisim < -0.5:
            puan += 15
            detay["dxy"] = f"Dolar zayıflıyor (%{dxy_degisim:+.2f}) — Gümüşe destek"
        else:
            detay["dxy"] = f"Dolar nötr (%{dxy_degisim:+.2f})"

        # Petrol korelasyonu (ters korelasyon)
        petrol_degisim = ctx.get("petrol_degisim_yuzde", 0) or 0
        if petrol_degisim > 1.5:
            puan -= 10
            detay["petrol"] = f"Petrol yükseliyor (%{petrol_degisim:+.2f}) — Risk artar"
        elif petrol_degisim < -1.5:
            puan += 10
            detay["petrol"] = f"Petrol düşüyor (%{petrol_degisim:+.2f})"
        else:
            detay["petrol"] = f"Petrol nötr (%{petrol_degisim:+.2f})"

        # SP500 korelasyonu
        sp500_degisim = ctx.get("sp500_degisim_yuzde", 0) or 0
        if sp500_degisim < -1.5:
            puan += 10
            detay["sp500"] = f"S&P500 düşüyor — Güvenli liman talebi artabilir"
        elif sp500_degisim > 1.5:
            puan -= 5
            detay["sp500"] = f"S&P500 yükseliyor — Risk iştahı açık"
        else:
            detay["sp500"] = f"S&P500 nötr"

        puan = max(0, min(100, puan))
        logger.info(f"Risk modülü: manip={manip_var}, puan={puan}")

        return {
            "modul": "risk",
            "puan": puan,
            "manipulasyon_var": manip_var,
            "manipulasyon_detay": manip_detay,
            "detay": detay,
        }

    except Exception as e:
        logger.error(f"Risk modülü hatası: {e}")
        return {
            "modul": "risk",
            "puan": 50,
            "manipulasyon_var": False,
            "manipulasyon_detay": [],
            "detay": {"hata": str(e)},
        }
