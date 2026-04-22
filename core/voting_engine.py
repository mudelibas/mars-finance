import logging
import config as cfg

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
    agirliklar = cfg.MODUL_AGIRLIKLARI[rejim]

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

    teknik_puan = modul_sonuclari.get("teknik", {}).get("puan", 50) or 0
    sinyal_uret = (teknik_puan >= 60)

    # ─── ETİKET (Kurul görüşü sadece etiketler) ──────────────
    esik_guclu = getattr(cfg, "GOrus_GUCLU", 80)
    esik_normal = getattr(cfg, "GORUS_ORTA", 65)
    esik_riskli = getattr(cfg, "GORUS_RISKLI", 50)

    if kurul_gorusu >= esik_guclu:
        sinyal_sinif = "GUCLU_AL"
        ikon = "🟢"
        etiket = "Güçlü Alım Sinyali"
    elif kurul_gorusu >= esik_normal:
        sinyal_sinif = "ORTA_AL"
        ikon = "🟡"
        etiket = "Normal Alım Sinyali"
    elif kurul_gorusu >= esik_riskli:
        sinyal_sinif = "RISKLI_AL"
        ikon = "🔴"
        etiket = "Riskli Alım Sinyali"
    else:
        # Kurul görüşü düşük olsa bile (teknik yeterliyse) sinyal üretim kararı ayrı verilir.
        sinyal_sinif = "RISKLI_AL"
        ikon = "🔴"
        etiket = "Riskli Alım Sinyali"

    # ─── SİNYAL ÜRET (sadece teknik puan ile) ────────────────
    if not sinyal_uret:
        sinyal = None
        ikon = "⏸️"
        etiket = "Sinyal Yok"
    else:
        sinyal = sinyal_sinif

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
