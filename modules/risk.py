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

def hesapla_stop_tp(fiyat_tl, atr_usd, usd_try, config):
    """ATR bazlı stop-loss ve take-profit hesabı."""
    if not atr_usd or not usd_try:
        return None, None

    atr_tl = (atr_usd / 31.1035) * usd_try
    makas = config.get("MAKAS_TL", 0.75)
    bsmv = config.get("BSMV_KMV_YUZDE", 0.2) / 100
    net_kar = config.get("NET_KAR_HEDEFI_YUZDE", 1.5) / 100
    tp_carp = config.get("ATR_CARPAN_TP", 2.5)
    sl_carp = config.get("ATR_CARPAN_SL", 1.0)

    # Gerçek giriş maliyeti
    giris_maliyeti = fiyat_tl + makas + (fiyat_tl * bsmv / 2)

    # Brüt hedef: net %1.5 + çıkış vergisi
    tp_tl = giris_maliyeti * (1 + net_kar) * (1 + bsmv / 2)

    # ATR bazlı minimum kontrol
    tp_atr = fiyat_tl + (atr_tl * tp_carp)
    tp_tl = max(tp_tl, tp_atr)

    sl_tl = fiyat_tl - (atr_tl * sl_carp)

    return round(tp_tl, 2), round(sl_tl, 2)

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
