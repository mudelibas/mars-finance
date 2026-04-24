# --- XAG scalping oylama: 0–100, yalnız eşik üstü; hacim+makro veto zorunluları ---

import logging
import config as cfg

logger = logging.getLogger(__name__)


def _rejim_belirle(ctx, _haber_sonuc):
    v = (ctx or {}).get("vix")
    if v and v > 32:
        return "kriz"
    return "scalp"


def hesapla(modul_sonuclari, ctx=None, haber_sonuc=None, haber_ignored=None):
    del haber_ignored
    _ = haber_sonuc
    rej = _rejim_belirle(ctx or {}, None)
    ag = cfg.MODUL_AGIRLIKLARI.get(
        rej, cfg.MODUL_AGIRLIKLARI.get("scalp", cfg.MODUL_AGIRLIKLARI["normal"])
    )

    makro = modul_sonuclari.get("makro", {})
    if bool(makro.get("veto_spike_makro")):
        logger.warning("VETO: DXY/10Y ani hareket (makro spike)")
        return {
            "kurul_gorusu": 0.0,
            "sinyal": None,
            "veto": True,
            "veto_neden": "Makro ani fiyat/verim zıplaması — sinyal yasak",
            "rejim": rej,
            "modul_detay": {},
        }

    h = modul_sonuclari.get("hacim", {})
    if h.get("hacim_spike_ok") is False and h:
        logger.warning("VETO: 5m hacim zorunlu S spike yok")
        return {
            "kurul_gorusu": 0.0,
            "sinyal": None,
            "veto": True,
            "veto_neden": "Hacim: zorunlu hacim patlaması yok",
            "rejim": rej,
            "modul_detay": {},
        }

    g = modul_sonuclari.get("gold", {})
    if g and g.get("xag_xau_uyum") is False and g.get("puan", 0) is not None:
        logger.warning("VETO/RED: XAU 5m XAG ile aynı yönde hizali değil")
        return {
            "kurul_gorusu": 0.0,
            "sinyal": None,
            "veto": True,
            "veto_neden": "XAU/USD 5m XAG ile hizalama yok (altın onay)",
            "rejim": rej,
            "modul_detay": {},
        }

    modul_detay = {}
    toplam, aw = 0.0, 0.0
    for isim, agir in ag.items():
        if isim in ("haberler", "panikci", "balina", "risk"):
            continue
        p = float(modul_sonuclari.get(isim, {}).get("puan", 0) or 0)
        katki = p * agir
        toplam += katki
        aw += agir
        modul_detay[isim] = {
            "puan": p,
            "agirlik": agir,
            "katki": round(katki, 2),
        }

    kurul = round(toplam / aw, 1) if aw else 0.0
    esk = float(getattr(cfg, "SINYAL_MIN_PUAN", 75.0))
    tdet = modul_sonuclari.get("teknik", {})
    trend_ok = bool(
        tdet.get("trend_continuation")
        and tdet.get("in_pullback_zone")
    )
    sinal = (kurul >= esk) and trend_ok

    sinif = "XAG_SCALP_AL" if sinal else None
    logger.info(
        f"[Oylama] kurul={kurul} esk={esk} trend+pullback={trend_ok} sinyal={sinal}"
    )
    return {
        "kurul_gorusu": float(kurul),
        "sinyal": sinif,
        "ikon": "▲" if sinal else "⏸",
        "etiket": "Scalp AL" if sinal else "Bekle",
        "veto": False,
        "veto_neden": None,
        "rejim": rej,
        "modul_detay": modul_detay,
    }
