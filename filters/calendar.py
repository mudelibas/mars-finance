import logging
import json
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

KILIT_DOSYA = "sinyal_kilidi.json"

def kilit_kontrol():
    """Aktif kilit var mı?"""
    if not os.path.exists(KILIT_DOSYA):
        return False, None
    with open(KILIT_DOSYA) as f:
        veri = json.load(f)
    bitis = datetime.fromisoformat(veri["bitis"])
    if datetime.now(timezone.utc) < bitis:
        return True, veri.get("neden", "Bilinmiyor")
    os.remove(KILIT_DOSYA)
    return False, None

def kilit_koy(dakika, neden):
    bitis = datetime.now(timezone.utc) + timedelta(minutes=dakika)
    with open(KILIT_DOSYA, "w") as f:
        json.dump({"bitis": bitis.isoformat(), "neden": neden}, f)
    logger.warning(f"Sinyal kilidi: {neden} ({dakika} dk)")
