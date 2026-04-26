import os

# ─── API anahtarları ─────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")
FRED_API_KEY = os.getenv("FRED_API_KEY")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")

# ─── Zamanlama (UTC) ───────────────────────────────────────
ANALIZ_SAATLERI_UTC = [5, 9, 13, 17, 21]
FIYAT_TAKIP_INTERVAL_DAKIKA = 5

# ─── EMA & hacim (trend) ────────────────────────────────────
EMA_TREND_HIZLI = 20
EMA_TREND_YAVAS = 50
HACIM_SPIKE_MIN_CARPAN = 1.15

# ─── Makro ani hareket eşikleri (tek mum) ───────────────────
MAKRO_DXY_ANI_ESIK = 0.5
MAKRO_TNX_ANI_ESIK = 0.3

# ─── VIX ────────────────────────────────────────────────────
VIX_PANIK = 30
VIX_IYIMSER = 15

# ─── Sinyal yönetimi & hedefler ─────────────────────────────
SINYAL_MAKS_AKTIF = 2
SINYAL_MAKS_OLCEKLE = 3
# Takvim kiliti / periyodik (main) — yoksa varsayılan
OLAY_ONCESI_DAKIKA = 15
VOLATILITE_BASLANGIC_HOUR = 12
VOLATILITE_BASLANGIC_MINUTE = 0
# ATR (ör. 15m) hedef: güçlü / zayıf senaryo çarpanları
ATR_CARPAN_TP_GUCLU = 2.5
ATR_CARPAN_TP_ZAYIF = 1.5
# Minimum net kâr yüzdesi (brüt-sonrası; maliyetler ayrı hesaplanır)
NET_KAR_MIN_YDE = 1.0
# Sabit vergi / kesinti yüzde (yüzde cinsinden, örn. 0.2 = %0.2 toplam hissi için kullanım modülde)
VERGI_YDE = 0.2
# Skor / sinyal eşiği (0–100 ölçekli skorlarda alt sınır)
SKOR_ESIK = 65
# SI = F (spot) vs TL türev sapma eşiği; baz bant yüzdesi
SAPMA_BAZ_YDE = 0.3
# Likidite sweep onayı sonrası beklenecek minimum bar sayısı
SWEEP_MIN_MUM = 3
# Piyasa verisinin taze sayılma süresi
STALE_DATA_DAKIKA = 15

# ─── RSS (news modülü; sadece URL, tier sözlüğü opsiyonel) ──
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
