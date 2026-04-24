import logging
from config import GROQ_API_KEY, MAKAS_TL, ATR_CARPAN_TP, ATR_CARPAN_SL
from core.data_engine import get_silver_price_tl, get_gold_price_tl, get_market_context
from core.voting_engine import hesapla
from modules.technical import calistir as teknik_calistir
from modules.quant import calistir as quant_calistir
from modules.behavioral import calistir as behavioral_calistir
from modules.news import calistir as haber_calistir
from modules.hacim import calistir as hacim_calistir
from filters.calendar import kilit_kontrol

logger = logging.getLogger(__name__)

try:
    from groq import Groq
    _groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except:
    _groq = None

# ─── LLM — SADECE AÇIKLAMA YAZICI ───────────────────────────

def _llm_sinyal_acikla(oylama, modul_sonuclari, fiyat_tl, tp_tl, sl_tl):
    """
    LLM sinyali Türkçe anlatır. Karar vermez, özetler.
    """
    if not _groq:
        return None

    modul_ozet = "\n".join([
        f"- {m}: {d['puan']}/100"
        for m, d in oylama["modul_detay"].items()
    ])

    haber_ozet = modul_sonuclari.get("haberler", {}).get("ozet", "")

    prompt = f"""Bir finansal karar destek sistemi tarafından üretilen sinyal verisi:

Kurul Görüşü: %{oylama['kurul_gorusu']}
Sinyal: {oylama['etiket']}
Makro Rejim: {oylama['rejim']}

Modül Puanları:
{modul_ozet}

Haber özeti: {haber_ozet or 'Kritik haber yok'}

Giriş: ₺{fiyat_tl:.2f}/gram
Hedef: ₺{tp_tl:.2f}/gram
Stop: ₺{sl_tl:.2f}/gram

Bu sinyali yatırımcıya 3-4 cümleyle sade Türkçe açıkla.
Neden bu sinyal oluştu? Hangi faktörler öne çıktı?
Kesinlikle tavsiye verme, sadece açıkla.
Başlık veya ek açıklama ekleme, sadece paragrafı yaz."""

    try:
        r = _groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=200,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"LLM açıklama hatası: {e}")
        return None

# ─── DURUM ANALİZİ (sinyal yokken) ──────────────────────────

def _llm_durum_ozeti(modul_sonuclari, fiyat_tl, ctx):
    if not _groq:
        return "Piyasa verisi alındı, analiz devam ediyor."

    modul_ozet = "\n".join([
        f"- {k}: {v.get('puan', 50)}/100"
        for k, v in modul_sonuclari.items()
        if isinstance(v, dict) and "puan" in v
    ])

    prompt = f"""Gümüş piyasası anlık durum:
Fiyat: ₺{fiyat_tl:.2f}/gram
VIX: {ctx.get('vix', 'N/A')}
DXY değişim: %{ctx.get('dxy_degisim_yuzde', 0):.2f}

Modül durumları:
{modul_ozet}

Piyasanın genel durumunu 2-3 cümleyle sade Türkçe özetle.
Sinyal yok ama neden? Ne bekleniyor?
Sadece paragrafı yaz, başlık ekleme."""

    try:
        r = _groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=300,
        )
        return r.choices[0].message.content.strip()
    except:
        return "Piyasa koşulları sinyal üretimi için yeterli değil."

# ─── ANA FONKSİYONLAR ───────────────────────────────────────

def tam_analiz_calistir(config):
    """
    Tüm modülleri paralel çalıştırır, kurul görüşü hesaplar.
    """
    # Kilit kontrolü
    kilit_var, kilit_neden = kilit_kontrol()
    if kilit_var:
        logger.info(f"Sinyal kilidi aktif: {kilit_neden}")
        return {
            "sinyal": None,
            "kilit": True,
            "kilit_neden": kilit_neden,
            "oylama": None,
            "modul_sonuclari": {},
        }

    modul_sonuclari = {}

    # Modülleri çalıştır
    for isim, fonk in [
        ("teknik",       lambda: teknik_calistir(config)),
        ("matematiksel", lambda: quant_calistir(config)),
        ("panikci",      lambda: behavioral_calistir(config)),
        ("haberler",     lambda: haber_calistir(config)),
        ("hacim",        lambda: hacim_calistir(config)),
    ]:
        try:
            modul_sonuclari[isim] = fonk()
        except Exception as e:
            logger.error(f"Modül hatası [{isim}]: {e}")
            modul_sonuclari[isim] = {"puan": 50, "detay": {}}

    ctx = get_market_context()
    haber_sonuc = modul_sonuclari.get("haberler", {})

    # Oylama motoru
    oylama = hesapla(modul_sonuclari, ctx=ctx, haber_sonuc=haber_sonuc)

    return {
        "oylama": oylama,
        "modul_sonuclari": modul_sonuclari,
        "ctx": ctx,
        "kilit": False,
        "kilit_neden": None,
    }

def sinyal_uret(config):
    """
    Tam analiz çalıştırır, sinyal varsa formatlar.
    """
    sonuc = tam_analiz_calistir(config)

    if sonuc["kilit"]:
        return False, f"⏸️ Sinyal kilidi: {sonuc['kilit_neden']}", None, None, None

    oylama = sonuc["oylama"]
    modul_sonuclari = sonuc["modul_sonuclari"]
    ctx = sonuc.get("ctx", {})

    if oylama["veto"]:
        return False, f"🚫 {oylama['veto_neden']}", None, None, None

    if not oylama["sinyal"]:
        fiyat_tl, _ = get_silver_price_tl()
        ozet = _llm_durum_ozeti(modul_sonuclari, fiyat_tl or 0, ctx)
        return False, ozet, None, None, None

    # Sinyal var — fiyat ve hedef hesapla
    fiyat_tl, usd_try = get_silver_price_tl()
    altin_tl, _ = get_gold_price_tl()

    atr = (modul_sonuclari.get("teknik", {})
           .get("atr_1h") or
           modul_sonuclari.get("matematiksel", {}).get("atr"))

    tp_tl, sl_tl = hesapla_stop_tp(fiyat_tl, atr, usd_try, config)

    if not fiyat_tl or not tp_tl:
        return False, "Fiyat verisi alınamadı.", None, None, None

    tp_yuzde = ((tp_tl - fiyat_tl) / fiyat_tl) * 100
    sl_yuzde = ((fiyat_tl - sl_tl) / fiyat_tl) * 100 if sl_tl else 0

    # LLM açıklama (sadece metin üretir)
    aciklama = _llm_sinyal_acikla(
        oylama, modul_sonuclari, fiyat_tl, tp_tl, sl_tl
    )

    # Mesaj formatla
    mesaj = _sinyal_mesaji_formatla(
        oylama, modul_sonuclari, fiyat_tl, altin_tl,
        tp_tl, sl_tl, tp_yuzde, sl_yuzde, aciklama
    )

    return True, mesaj, fiyat_tl, tp_tl, oylama["sinyal"]

def _sinyal_mesaji_formatla(oylama, modüller, fiyat_tl, altin_tl,
                            tp_tl, sl_tl, tp_yuzde, sl_yuzde, aciklama):
    ikon   = oylama["ikon"]
    etiket = oylama["etiket"]
    kgorus = oylama["kurul_gorusu"]

    # Modül satırları
    modul_isimleri = {
        "teknik":       "Teknik Analiz   ",
        "matematiksel": "Matematiksel     ",
        "haberler":     "Jeopolitik       ",
        "balina":       "Balina Faktörü   ",
        "panikci":      "Panikçi Faktör   ",
        "risk":         "Risk             ",
        "hacim":        "Hacim Anomalisi ",
    }

    modul_satirlari = []
    for k, isim in modul_isimleri.items():
        puan = modüller.get(k, {}).get("puan", 50)
        if puan >= 70:
            m_ikon = "✅"
        elif puan >= 50:
            m_ikon = "⚠️"
        else:
            m_ikon = "❌"
        modul_satirlari.append(f"  {m_ikon} {isim}: {puan:.0f}/100")

    altin_str = f"₺{altin_tl:.2f}/gram" if altin_tl else "N/A"

    return (
        f"{ikon} {etiket}\n"
        f"Kurul Görüşü: %{kgorus:.0f}\n\n"
        f"💰 Gümüş: ₺{fiyat_tl:.2f}/gram\n"
        f"🥇 Altın:  {altin_str}\n\n"
        f"📍 Giriş : ₺{fiyat_tl:.2f}\n"
        f"🎯 Hedef : ₺{tp_tl:.2f} (+%{tp_yuzde:.1f})\n"
        f"🛑 Stop  : ₺{sl_tl:.2f} (-%{sl_yuzde:.1f})\n\n"
        f"📊 Modül Oyları:\n"
        + "\n".join(modul_satirlari) +
        f"\n\n💬 {aciklama or 'Analiz tamamlandı.'}\n\n"
        f"_Yatırım tavsiyesi değildir. En doğrusunu Allah bilir._"
    )

def build_hedef_mesaji(giris_tarihi, giris_tl, mevcut_tl, config):
    """
    Hedefe ulaşıldığında Telegram mesajı ve net kâr yüzdesi üretir.

    Parametreler:
    - giris_tarihi: string (ör. "2026-04-22 12:34")
    - giris_tl: giriş fiyatı (TL/gram)
    - mevcut_tl: anlık fiyat (TL/gram)
    - config: config dict
    """
    makas = config.get("MAKAS_TL", 0.75)
    bsmv = config.get("BSMV_KMV_YUZDE", 0.2) / 100  # toplam (giriş+çıkış)

    giris_maliyeti = giris_tl + makas + (giris_tl * bsmv / 2)
    net_cikis = mevcut_tl - (mevcut_tl * bsmv / 2)
    net_kar_yuzde = ((net_cikis - giris_maliyeti) / giris_maliyeti) * 100 if giris_maliyeti else 0

    mesaj = (
        f"🎯 Hedef Görüldü\n\n"
        f"Giriş ({giris_tarihi or '--'}): ₺{giris_tl:.2f} → Şu an: ₺{mevcut_tl:.2f}\n"
        f"Net kâr: +%{net_kar_yuzde:.1f}\n\n"
        f"_Nefsinin tamahkarlığından korunabilmiş kimseler, "
        f"işte onlar saadete erenlerdir. — Haşr 9_"
    )
    return mesaj, net_kar_yuzde

def durum_analizi_calistir(config):
    """Sinyal yokken sabah/periyodik durum özeti."""
    sonuc = tam_analiz_calistir(config)
    if sonuc["kilit"]:
        return f"⏸️ {sonuc['kilit_neden']}"

    oylama = sonuc["oylama"]
    modul_sonuclari = sonuc["modul_sonuclari"]
    ctx = sonuc.get("ctx", {})

    fiyat_tl, _ = get_silver_price_tl()
    altin_tl, _ = get_gold_price_tl()

    ozet = _llm_durum_ozeti(modul_sonuclari, fiyat_tl or 0, ctx)

    vix   = ctx.get("vix") or 0
    dxy_d = ctx.get("dxy_degisim_yuzde", 0) or 0
    pet_d = ctx.get("petrol_degisim_yuzde", 0) or 0
    gum_d = ctx.get("gumus_degisim_yuzde", 0) or 0
    alt_d = ctx.get("altin_degisim_yuzde", 0) or 0

    def vix_icon(v): return "🟢" if v < 15 else "🔴" if v > 30 else "🔘"
    def dolar_icon(d): return "🟢" if d < -0.3 else "🔴" if d > 0.3 else "🔘"

    return (
        f"📊 Piyasa Durumu\n\n"
        f"🪙 Gümüş: ₺{fiyat_tl:.2f} (%{gum_d:+.2f})\n"
        f"🥇 Altın:  ₺{altin_tl:.2f} (%{alt_d:+.2f})\n"
        f"😨 Korku Endeksi: {vix:.1f} {vix_icon(vix)}\n"
        f"💵 Dolar Endeksi: %{dxy_d:+.2f} {dolar_icon(dxy_d)}\n"
        f"🛢️ Petrol: ${ctx.get('petrol', 0):.1f} (%{pet_d:+.2f})\n\n"
        f"Kurul Görüşü: %{oylama['kurul_gorusu']:.0f} "
        f"({oylama['etiket']})\n\n"
        f"{ozet}"
    ) if fiyat_tl else "Piyasa verisi alınamadı."