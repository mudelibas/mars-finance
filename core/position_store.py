# --- Açık sinyal takibi: en fazla 2 aktif, sinyal başına en fazla 3 ölçekleme (yer tutucu) ---

import json
import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import SINYAL_MAKS_AKTIF, SINYAL_MAKS_OLCEKLE

logger = logging.getLogger(__name__)
DOSYA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "open_positions.json")
TR = timezone(timedelta(hours=3))


def _yukle():
    if not os.path.exists(DOSYA):
        return {"signals": []}
    with open(DOSYA, encoding="utf-8") as f:
        return json.load(f)


def _kaydet(data):
    with open(DOSYA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def acik_sinyal_sayisi():
    d = _yukle()
    return len([s for s in d["signals"] if s.get("status") == "OPEN"])


def yeni_alim_ekle(
    entry_usd=0.0,
    tp_usd=0.0,
    confidence=0.0,
    reason_short="",
    telemesaj_id=None,
    meta=None,
    giris_tl=None,
    hedef_tl=None,
    atr_half_tl=None,
):
    """
    Açık sinyal (tercihen Dünya Katılım TL: giris / hedef / ATR/2 ters bölge takibi).
    Gerekirse legacy USD/oz: entry_target_usd / tp_usd.
    """
    if acik_sinyal_sayisi() >= SINYAL_MAKS_AKTIF:
        logger.info(f"[pozisyon] yeni sinyal reddedildi: max {SINYAL_MAKS_AKTIF} açık")
        return None
    sid = str(uuid.uuid4())[:12]
    now = datetime.now(TR).strftime("%Y-%m-%d %H:%M:%S")
    rec = {
        "id": sid,
        "status": "OPEN",
        "entry_target_usd": float(entry_usd) if entry_usd else 0.0,
        "tp_usd": float(tp_usd) if tp_usd else 0.0,
        "giris_tl": float(giris_tl) if giris_tl is not None else None,
        "hedef_tl": float(hedef_tl) if hedef_tl is not None else None,
        "atr_half_tl": float(atr_half_tl) if atr_half_tl is not None else None,
        "scales_filled": 0,
        "scales_max": SINYAL_MAKS_OLCEKLE,
        "created": now,
        "confidence": float(confidence or 0.0),
        "reason": reason_short or "",
        "telegram_message_id": telemesaj_id,
        "meta": meta or {},
        "early_80_alerts_sent": False,
    }
    d = _yukle()
    d["signals"].append(rec)
    _kaydet(d)
    logger.info(
        f"[pozisyon] OPEN sinyal={sid} giris_tl={rec['giris_tl']} "
        f"hedef={rec['hedef_tl']}"
    )
    return rec


def tüm_acikler():
    return [s for s in _yukle()["signals"] if s.get("status") == "OPEN"]


def sinyal_kapat(
    sinyal_id, cikis_usd: float = 0.0, neden: str = "TP", cikis_tl: Optional[float] = None
):
    d = _yukle()
    for s in d["signals"]:
        if s.get("id") == sinyal_id and s.get("status") == "OPEN":
            s["status"] = "CLOSED"
            s["closed"] = datetime.now(TR).strftime("%Y-%m-%d %H:%M:%S")
            s["exit_usd"] = float(cikis_usd) if cikis_usd else 0.0
            s["cikis_tl"] = float(cikis_tl) if cikis_tl is not None else None
            s["close_reason"] = neden
            e_usd = s.get("entry_target_usd")
            e_tl = s.get("giris_tl")
            if cikis_tl is not None and e_tl and float(e_tl) > 0:
                s["pnl_gross_pct"] = round(
                    (float(cikis_tl) - float(e_tl)) / float(e_tl) * 100, 3
                )
            elif e_usd and float(e_usd) > 0 and cikis_usd:
                s["pnl_gross_pct"] = round(
                    (float(cikis_usd) - float(e_usd)) / float(e_usd) * 100, 3
                )
            _kaydet(d)
            logger.info(f"[pozisyon] kapatıldı id={sinyal_id} neden={neden}")
            return s
    return None


def early_alert_isaretle(sinyal_id):
    d = _yukle()
    for s in d["signals"]:
        if s.get("id") == sinyal_id and s.get("status") == "OPEN":
            s["early_80_alerts_sent"] = True
            _kaydet(d)
            return


def tüm_kayitlar():
    return _yukle().get("signals", [])


def istatistik_ozet():
    """Aktif sayı, kapanan, 24h üstü açık."""
    d = _yukle()["signals"]
    now = datetime.now(TR)
    t24 = now - timedelta(hours=24)
    açık = [s for s in d if s.get("status") == "OPEN"]
    kapalı = [s for s in d if s.get("status") == "CLOSED"]
    eski_24h = 0
    for s in açık:
        try:
            ts = s.get("created", "")
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TR)
        except (ValueError, TypeError):
            eski_24h += 1
            continue
        if (now - dt) > timedelta(hours=24):
            eski_24h += 1
    kazançlı = 0
    for s in kapalı:
        p = s.get("pnl_gross_pct")
        try:
            if p is not None and float(p) > 0:
                kazançlı += 1
        except (TypeError, ValueError):
            pass
    n_kap = len(kapalı)
    success_rate_pct = round(100.0 * kazançlı / n_kap, 1) if n_kap else None

    return {
        "active_count": len(açık),
        "closed_count": n_kap,
        "open_older_24h": eski_24h,
        "wins": kazançlı,
        "success_rate_pct": success_rate_pct,
    }