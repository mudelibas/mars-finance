import logging
from config import MODUL_AGIRLIKLARI, GOrus_GUCLU, GORUS_ORTA, GORUS_RISKLI

logger = logging.getLogger(__name__)

def _rejim_belirle(ctx, haber_sonuc):
    """Hangi ağırlık seti kullanılacak?"""
    vix = ctx.get("vix") or 20
    haber_kritik = haber_sonuc.get("kritik", False) if haber_sonuc else False

    if vix > 30 or haber_kritik:
        return "kriz"

    # Trend tespiti: DXY + MA sinyali + COT aynı yönde ise
    # (basit versiyon — balina ve teknik puan yüksekse trend)
    return "normal"

def hesapla(modul_sonuclari, ctx=None, haber_sonuc=None):
    """
    Tüm modül sonuçlarını alır, ağırlıklı kurul görüşü hesaplar.

    modul_sonuclari: dict — her modülün {'puan': X} sonucu
    döner: kurul_gorusu (0-100), sinyal_tipi, detay
    """
    rejim = _rejim_belirle(ctx or {}, haber_sonuc)
    agirliklar = MODUL_AGIRLIKLARI[rejim]

    # ─── VETO KONTROLLARI ───────────────────────────────────
    # 1. Manipülasyon veto
    risk = modul_sonuclari.get("risk", {})
    if risk.get("manipulasyon_var", False):
        logger.warning("VETO: Manipülasyon tespiti")
        return {
            "kurul_gorusu": 0,
            "sinyal": None,
            "veto": True,
            "veto_neden": "Manipülasyon tespiti: " + 
                          " | ".join(risk.get("manipulasyon_detay", [])),
            "rejim": rejim,
            "detay": {},
        }

    # 2. Makro rejim veto (deflasyonist ortamda puan çok düşükse)
    makro = modul_sonuclari.get("makro", {})
    if makro.get("puan", 50) < 25:
        logger.warning("VETO: Makro rejim uyumsuzluğu")
        return {
            "kurul_gorusu": 0,
            "sinyal": None,
            "veto": True,
            "veto_neden": f"Makro rejim uyumsuz: {makro.get('rejim_str', '')}",
            "rejim": rejim,
            "detay": {},
        }

    # ─── AĞIRLIKLI PUAN ─────────────────────────────────────
    modul_map = {
        "teknik":       modul_sonuclari.get("teknik", {}).get("puan", 50),
        "matematiksel": modul_sonuclari.get("matematiksel", {}).get("puan", 50),
        "haberler":     modul_sonuclari.get("haberler", {}).get("puan", 50),
        "balina":       modul_sonuclari.get("balina", {}).get("puan", 50),
        "panikci":      modul_sonuclari.get("panikci", {}).get("puan", 50),
        "risk":         modul_sonuclari.get("risk", {}).get("puan", 50),
        "makro":        modul_sonuclari.get("makro", {}).get("puan", 50),
    }

    toplam_puan = 0
    agirlik_toplam = 0
    modul_detay = {}

    for modul, puan in modul_map.items():
        agirlik = agirliklar.get(modul, 0)
        katki   = puan * agirlik
        toplam_puan += katki
        agirlik_toplam += agirlik
        modul_detay[modul] = {
            "puan": puan,
            "agirlik": agirlik,
            "katki": round(katki, 2),
        }

    kurul_gorusu = round(toplam_puan, 1)

    # ─── SİNYAL TİPİ ────────────────────────────────────────
    if kurul_gorusu >= GOrus_GUCLU:
        sinyal = "GUCLU_AL"
        ikon   = "🟢"
        etiket = "Güçlü Alım Sinyali"
    elif kurul_gorusu >= GORUS_ORTA:
        sinyal = "ORTA_AL"
        ikon   = "🟡"
        etiket = "Orta Alım Sinyali"
    elif kurul_gorusu >= GORUS_RISKLI:
        sinyal = "RISKLI_AL"
        ikon   = "🔴"
        etiket = "Riskli Alım Sinyali"
    else:
        sinyal = None
        ikon   = "⏸️"
        etiket = "Sinyal Yok"

    logger.info(
        f"Kurul Görüşü: %{kurul_gorusu} [{etiket}] | Rejim: {rejim}"
    )

    return {
        "kurul_gorusu": kurul_gorusu,
        "sinyal": sinyal,
        "ikon": ikon,
        "etiket": etiket,
        "veto": False,
        "veto_neden": None,
        "rejim": rejim,
        "modul_detay": modul_detay,
    }
