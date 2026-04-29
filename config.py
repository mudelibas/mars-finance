import os

# ─── API anahtarları ─────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")

STALE_DATA_DAKIKA = 15

# ─── RSS Kaynakları ──────────────────────────────────────────
RSS_KAYNAKLAR = {
    "finans": [
        "https://www.bloomberght.com/rss",
    ],
    "siyasi": [
        "https://www.aa.com.tr/tr/rss/default?cat=dunya",
        "https://www.aa.com.tr/tr/rss/default?cat=politika",
    ],
}

# ─── Haber Filtre Kelimeleri ─────────────────────────────────
HABER_FILTRE = {
    "finans": [
        "altın", "gümüş", "dolar", "faiz", "enflasyon",
        "merkez bankası", "fed", "borsa", "emtia", "petrol",
        "döviz", "euro", "sterlin", "brent", "ham petrol",
    ],
    "siyasi": [
        "trump", "israil", "ortadoğu", "suriye", "rusya",
        "savaş", "gerilim", "hürmüz", "yaptırım", "iran",
        "ateşkes", "barış", "çatışma", "gerginlik",
    ],
}