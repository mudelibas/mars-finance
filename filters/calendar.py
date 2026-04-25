# Takvim / olay kilidi (yer tutucu — genişletilebilir)
import logging

logger = logging.getLogger(__name__)


def kilit_kontrol():
    """(kilit_var, neden) — şu an her zaman açık."""
    return False, None


def kilit_koy(dakika: int, neden: str) -> None:
    """Gelecekte: belirli süre sinyal kilidi. Şimdilik yalnız log."""
    logger.info("Kilit (yer tutucu): %s dk — %s", int(dakika), neden)
