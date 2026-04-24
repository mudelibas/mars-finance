import logging
from config import GROQ_API_KEY
from core.data_engine import get_silver_price_tl, get_gold_price_tl, get_market_context
from core.voting_engine import hesapla
from modules.risk import hesapla_stop_tp
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
except Exception as e:
    logger.error(f"Groq istemcisi başlatılamadı: {e}")
    _groq = None

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
    except Exception as e:
        logger.error(f"LLM durum özeti hatası: {e}")
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

    atr = (modul_sonuclari.get("teknik", {})
           .get("atr_1h") or
           modul_sonuclari.get("matematiksel", {}).get("atr"))

    tp_tl, sl_tl = hesapla_stop_tp(fiyat_tl, atr, usd_try, config)

    if not fiyat_tl or not tp_tl:
        return False, "Fiyat verisi alınamadı.", None, None, None

    mesaj = _sinyal_mesaji_formatla(fiyat_tl, tp_tl)

    return True, mesaj, fiyat_tl, tp_tl, oylama["sinyal"]

def _sinyal_mesaji_formatla(fiyat_tl, tp_tl):
    return (
        f"Gümüş\n"
        f"AL\n"
        f"Giriş: ₺{fiyat_tl:.2f}\n"
        f"Hedef: ₺{tp_tl:.2f}\n"
    )

def build_hedef_mesaji(_giris_tarihi, giris_tl, hedef_tl, mevcut_tl, config):
    """
    Hedefe ulaşındığında kısa SAT metni ve net kâr yüzdesi.
    mevcut_tl: çıkış fiyatı (kâr hesabı); hedef_tl: plandaki hedef.
    """
    makas = config.get("MAKAS_TL", 0.75)
    bsmv = config.get("BSMV_KMV_YUZDE", 0.2) / 100  # toplam (giriş+çıkış)

    giris_maliyeti = giris_tl + makas + (giris_tl * bsmv / 2)
    net_cikis = mevcut_tl - (mevcut_tl * bsmv / 2)
    net_kar_yuzde = ((net_cikis - giris_maliyeti) / giris_maliyeti) * 100 if giris_maliyeti else 0

    mesaj = (
        f"Gümüş\n"
        f"SAT\n"
        f"Giriş: ₺{giris_tl:.2f}\n"
        f"Hedef: ₺{hedef_tl:.2f}\n"
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