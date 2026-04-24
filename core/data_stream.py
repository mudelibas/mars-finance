# ─── Gerçek zaman: WebSocket tercih, yoksa REST (yfinance) fallback ─
# Düşük gecikme için: üretimde ayrı WS aracı/SAAS anahtarları eklenebilir.

import logging

logger = logging.getLogger(__name__)

# Şu an ek bağımlılık yok; ileride örn. websocket-client ile borsa akışı
_WS_ATTEMPTED = False


def get_streaming_mode() -> str:
    """'websocket' veya 'rest' — sadece log/telemetri."""
    return "rest"


def log_data_source(sembol: str) -> None:
    """Hangi yolla fiyat alındığını tekrar edilebilir test için yazar."""
    m = get_streaming_mode()
    logger.info(f"[XAG/veri] {sembol} kaynağı={m} (WS tercih; yoksa REST)")
