import logging
import config as cfg0
from config import GROQ_API_KEY
from core.data_engine import get_silver_price_tl, get_gold_price_tl, get_market_context
from core.voting_engine import hesapla
from modules.risk import hesapla_profit_target_usd, fiyat_erkun_esigi
from modules.technical import calistir as teknik_calistir
from modules.quant import calistir as quant_calistir
from modules.hacim import calistir as hacim_calistir
from modules.gold import calistir as gold_calistir
from filters.macro_regime import belirle as makro_belirle
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
    # XAGUSD scalping: 1m/5m/15m trend, hacim, quant ADX, makro (DXY+TNX), altın onay
    for isim, fonk in [
        ("teknik",       lambda: teknik_calistir(config)),
        ("matematiksel", lambda: quant_calistir(config)),
        ("hacim",        lambda: hacim_calistir(config)),
    ]:
        try:
            modul_sonuclari[isim] = fonk()
        except Exception as e:
            logger.error(f"Modül hatası [{isim}]: {e}")
            modul_sonuclari[isim] = {"modul": isim, "puan": 0, "detay": {}}
    try:
        modul_sonuclari["makro"] = makro_belirle(config)
    except Exception as e:
        logger.error(f"Modül hatası [makro]: {e}")
        modul_sonuclari["makro"] = {"modul": "makro", "puan": 0, "veto_spike_makro": True, "detay": {}}
    try:
        modul_sonuclari["gold"] = gold_calistir(config)
    except Exception as e:
        logger.error(f"Modül hatası [gold]: {e}")
        modul_sonuclari["gold"] = {"modul": "gold", "puan": 0, "xag_xau_uyum": False, "detay": {}}

    ctx = get_market_context()
    oylama = hesapla(modul_sonuclari, ctx=ctx, haber_sonuc=None)

    return {
        "oylama": oylama,
        "modul_sonuclari": modul_sonuclari,
        "ctx": ctx,
        "kilit": False,
        "kilit_neden": None,
    }

def sinyal_uret(config):
    """
    Tam analiz; onay varsa: LIMIT giriş (USD/oz), yalnız kâr hedefi, Telegram metni.
    6'lı: (ok, metin, entry_usd, tp_usd, tip, meta|None)
    """
    sonuc = tam_analiz_calistir(config)

    if sonuc["kilit"]:
        return False, f"⏸️ Sinyal kilidi: {sonuc['kilit_neden']}", None, None, None, None

    oylama = sonuc["oylama"]
    modul_sonuclari = sonuc["modul_sonuclari"]
    ctx = sonuc.get("ctx", {})

    if oylama is None or oylama.get("veto"):
        n = oylama.get("veto_neden", "Bilinmiyor") if oylama else "—"
        return False, f"🚫 {n}", None, None, None, None

    if not oylama.get("sinyal"):
        fiyat_tl, _ = get_silver_price_tl()
        ozet = _llm_durum_ozeti(modul_sonuclari, fiyat_tl or 0, ctx)
        return False, ozet, None, None, None, None

    t = modul_sonuclari.get("teknik", {})
    entry_usd = t.get("entry_limit_usd_oz") or t.get("fiyat_usd")
    if not entry_usd or entry_usd <= 0:
        return False, "Giriş (USD/oz) türetilemedi.", None, None, None, None

    tp_usd = hesapla_profit_target_usd(float(entry_usd), config)
    conf = float(oylama.get("kurul_gorusu", 0))
    r1, r2 = _kisa_gerekce(modul_sonuclari, oylama)
    meta = {
        "confidence": round(conf, 1),
        "reason": f"{r1}\n{r2}",
        "entry_usd": float(entry_usd),
        "tp_usd": float(tp_usd),
    }
    mesaj = _sinyal_telegram_xag(
        float(entry_usd), float(tp_usd), int(round(conf)), r1, r2
    )
    return True, mesaj, float(entry_usd), float(tp_usd), oylama["sinyal"], meta


def _kisa_gerekce(mod, o):
    t = mod.get("teknik", {}).get("detay", {})
    m = mod.get("makro", {}).get("detay", {})
    r1 = f"Kurul {o.get('kurul_gorusu', 0):.0f}/100 — 15m+5m trend, 1m VEMA geri çekilme"
    r2 = f"MTF XAG: {t.get('15m', '—')[:80]}"
    if m:
        r2 = (r2 + f" | Makro: {m.get('DXY_roc', '')}")[:200]
    return r1[:120], r2[:120]


def _sinyal_telegram_xag(entry, tp, confidence, r1, r2):
    np = (getattr(cfg0, "NET_TP_MIN_PCT", 0.75) + getattr(cfg0, "NET_TP_MAX_PCT", 1.0)) / 2.0
    return (
        f"XAG/USD (scalp)\n"
        f"Entry: ${entry:.4f} / oz (limit bölge)\n"
        f"TP: ${tp:.4f} / oz (hedef ~net % {np:.2f}; spread+maliyet serpiştirme)\n"
        f"Güven: {confidence} / 100\n"
        f"—\n"
        f"{r1}\n"
        f"{r2}\n"
    )

def build_kapanis_mesaji_usd(giris_usd, hedef_usd, cikis_usd, config):
    """Kârda kapanış (XAG USD); yalnız TP / kâr onayı (profit-only, zorunlu kapatma yok)."""
    if not cikis_usd or not giris_usd or float(cikis_usd) < float(giris_usd):
        return "Kapanış: spot girişin altında — (profit-only, tetik yok).", 0.0
    net_brut = ((float(cikis_usd) - float(giris_usd)) / float(giris_usd) * 100) if giris_usd else 0.0
    mesaj = (
        f"XAG/USD kapanış (TP)\n"
        f"Giriş: ${float(giris_usd):.4f}\n"
        f"TP hedef: ${float(hedef_usd):.4f}\n"
        f"Çıkış: ${float(cikis_usd):.4f}  (brüt % {net_brut:+.2f})\n"
    )
    return mesaj, float(net_brut)


def build_hedef_mesaji(_giris_tarihi, giris_tl, hedef_tl, mevcut_tl, config):
    """
    TL tabanlı geri uyum (eski log). Yeni akış: build_kapanis_mesaji_usd.
    """
    makas = config.get("MAKAS_TL", 0.75)
    bsmv = config.get("BSMV_KMV_YUZDE", 0.2) / 100
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