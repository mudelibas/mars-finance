import os
from dotenv import load_dotenv

load_dotenv()

# ─── API ────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
FRED_API_KEY = os.getenv("FRED_API_KEY")

# ─── ZAMANLAMA (UTC) ─────────────────────────────────────────
ANALIZ_SAATLERI_UTC = [5, 9, 13, 17, 21]
SABAH_MESAJI_SAAT = 4
SABAH_MESAJI_DAKIKA = 55
FIYAT_TAKIP_INTERVAL_DAKIKA = 5
HABER_KONTROL_INTERVAL_DAKIKA = 5

PIYASA_ACILIS = [
    {"isim": "Tokyo",               "hour": 23, "minute": 55},
    {"isim": "Şangay",              "hour": 1,  "minute": 25},
    {"isim": "Londra ve Frankfurt", "hour": 6,  "minute": 55},
    {"isim": "New York (COMEX)",    "hour": 13, "minute": 25},
]

VOLATILITE_BASLANGIC_HOUR = 13
VOLATILITE_BASLANGIC_MINUTE = 20
VOLATILITE_BITIS_HOUR = 15
VOLATILITE_BITIS_MINUTE = 20

# ─── KURUL GÖRÜŞÜ EŞİKLERİ ──────────────────────────────────
GOrus_GUCLU = 80       # %80+ → Güçlü Sinyal 🟢
GORUS_ORTA = 65        # %65-79 → Normal Sinyal 🟡
GORUS_RISKLI = 50      # %50-64 → Riskli Sinyal 🔴
GORUS_SESSIZ = 0       # <%60 → Sessizlik

# ─── MODÜL AĞIRLIKLARI ───────────────────────────────────────
# Normal / Kriz / Trend
MODUL_AGIRLIKLARI = {
    "normal": {
        "teknik":       0.375,  # 0.275 + 0.10 (risk)
        "matematiksel": 0.275,  # 0.20 + 0.075 (balina/2)
        "haberler":     0.15,
        "panikci":      0.15,
        "hacim":        0.05,
    },
    "kriz": {
        "teknik":       0.30,   # 0.20 + 0.10 (risk)
        "matematiksel": 0.20,   # 0.15 + 0.05 (balina/2)
        "haberler":     0.35,
        "panikci":      0.15,
        "hacim":        0.00,
    },
    "trend": {
        "teknik":       0.45,   # 0.35 + 0.10 (risk)
        "matematiksel": 0.25,   # 0.20 + 0.05 (balina/2)
        "haberler":     0.10,
        "panikci":      0.10,
        "hacim":        0.05,
    },
}

# ─── TEKNİK PARAMETRELERİ ────────────────────────────────────
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 68
COT_MAX_SHORT_RATIO = 65.0

# ─── RİSK PARAMETRELERİ ──────────────────────────────────────
MAKAS_TL = 0.75
NET_KAR_HEDEFI_YUZDE = 1.5
BSMV_KMV_YUZDE = 0.2      # Giriş + çıkış toplam vergi %0.2
ATR_CARPAN_TP = 2.5        # 15dk ATR çarpanı hedef için
ATR_CARPAN_SL = 1.0        # 15dk ATR çarpanı stop için
KUMULATIF_BILDIRIM_ESIGI = 30.0

# ─── MANİPÜLASYON TESPİTİ ───────────────────────────────────
HACIM_ANOMALI_CARPAN = 3.0       # 20 günlük ortalamanın 3 katı
FIYAT_SPIKE_YUZDE = 3.0          # 5 mumda %3 ani hareket
STALE_DATA_DAKIKA = 15           # 15 dk güncellenmemiş veri

# ─── OLAY KİLİDİ ────────────────────────────────────────────
OLAY_ONCESI_DAKIKA = 120         # Takvimli olay öncesi 2 saat
OLAY_SONRASI_DAKIKA = 15         # Olay sonrası 15 dk
HABER_KILIDI_DAKIKA = 30         # Anlık şok sonrası 30 dk
HABER_KILIDI_ESIGI = 70          # Haber skoru bu eşiği geçerse kilit

# ─── BALON TESPİTİ ──────────────────────────────────────────
GSR_TARIHI_ORT = 65.0            # Gold/Silver Ratio tarihi ortalama
GSR_ZSCORE_ESIK = 2.0            # Z-Score eşiği

# ─── VOLATİLİTE REJİMLERİ ────────────────────────────────────
VIX_PANIK = 30
VIX_IYIMSER = 15
VOLATILITE_YUKSEK_ESIK = 0.025   # GARCH %2.5 üzeri = yüksek

# ─── HABER KAYNAKLARI (Tier bazlı) ──────────────────────────
RSS_KAYNAKLAR = {
    "kritik": [
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://apnews.com/rss",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.middleeasteye.net/rss",
    ],
    "önemli": [
        "https://rss.politico.com/politics-news.xml",
        "https://www.hellenicshippingnews.com/feed/",
        "https://oilprice.com/rss/main",
    ],
    "hammadde": [
        "https://silverseek.com/rss.xml",
    ],
    "genel": [
        "https://www.ft.com/rss/home/uk",
    ],
}

TIER_AGIRLIKLARI = {
    "kritik": 0.40,
    "önemli": 0.30,
    "hammadde": 0.20,
    "genel": 0.10,
}

# ─── KRİTİK HABER ANAHTAR KELİMELERİ ───────────────────────
KRITIK_KELIMELER = [
    # Ortadoğu / Jeopolitik
    "iran", "israel", "gaza", "lebanon", "syria", "yemen", "hormuz",
    "middle east", "ortadoğu", "hürmüz", "savaş", "war", "attack",
    # Ekonomi / Politika
    "trump", "fed", "federal reserve", "interest rate", "faiz",
    "inflation", "enflasyon", "cpi", "nfp", "tariff", "sanction",
    # Emtia
    "silver", "gold", "gümüş", "altın", "comex", "xag", "xau",
    "dollar", "dolar", "dxy",
    # Petrol
    "oil", "petrol", "opec", "crude",
]
