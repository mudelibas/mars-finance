import logging
import json
import os
import hashlib
import feedparser
from groq import Groq
from datetime import datetime, timezone, timedelta
from config import GROQ_API_KEY, RSS_KAYNAKLAR, TIER_AGIRLIKLARI, KRITIK_KELIMELER

logger = logging.getLogger(__name__)

def _entry_zaman(entry):
    try:
        import time as _time
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            utc = datetime(*t[:6], tzinfo=timezone.utc)
            tr = utc.astimezone(timezone(timedelta(hours=3)))
            return tr.strftime("%H:%M")
    except:
        pass
    return datetime.now(timezone(timedelta(hours=3))).strftime("%H:%M")

GORULMUS_DOSYA = "gorulmus_haberler.json"

try:
    _groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except:
    _groq = None

# ─── YARDIMCI ───────────────────────────────────────────────

def _haber_id(entry):
    return hashlib.md5(
        (entry.get("title", "") + entry.get("link", "")).encode()
    ).hexdigest()

def _gorulmus_oku():
    if os.path.exists(GORULMUS_DOSYA):
        with open(GORULMUS_DOSYA) as f:
            return set(json.load(f))
    return set()

def _gorulmus_kaydet(s):
    with open(GORULMUS_DOSYA, "w") as f:
        json.dump(list(s)[-500:], f)

def _on_filtre(baslik):
    """Kritik kelime içermiyor mu? Filtrelenir."""
    b = baslik.lower()
    return any(k in b for k in KRITIK_KELIMELER)

# ─── HABER ÇEKME ────────────────────────────────────────────

def yeni_haberler_cek():
    gorulmus = _gorulmus_oku()
    toplam = []

    for tier, kaynaklar in RSS_KAYNAKLAR.items():
        agirlik = TIER_AGIRLIKLARI.get(tier, 0.1)
        for kaynak in kaynaklar:
            try:
                feed = feedparser.parse(kaynak)
                for entry in feed.entries[:10]:
                    hid = _haber_id(entry)
                    if hid in gorulmus:
                        continue
                    baslik = entry.get("title", "")
                    if not _on_filtre(baslik):
                        gorulmus.add(hid)
                        continue
                    toplam.append({
                        "id": hid,
                        "tier": tier,
                        "agirlik": agirlik,
                        "title": baslik,
                        "summary": entry.get("summary", "")[:300],
                        "link": entry.get("link", ""),
                        "zaman": _entry_zaman(entry),
                    })
                    gorulmus.add(hid)
            except Exception as e:
                logger.error(f"RSS hatası ({kaynak}): {e}")

    _gorulmus_kaydet(gorulmus)
    logger.info(f"Filtrelenmiş yeni haber: {len(toplam)}")
    return toplam

# ─── LLM — SADECE ÇEVIRI ────────────────────────────────────

def _llm_haber_skoru(haberler):
    if not _groq or not haberler:
        return 0, []

    kritik = [h for h in haberler if h["tier"] == "kritik"][:3]
    diger = [h for h in haberler if h["tier"] != "kritik"][:3]
    secilen = (kritik + diger)[:6]

    haber_metni = "\n".join([
        f"[{h['tier'].upper()}] {h['title']}"
        for h in secilen
    ])

    prompt = f"""Aşağıdaki finansal/jeopolitik haberleri analiz et.
Her haberin gümüş (XAG) fiyatına olası etkisini değerlendir.

Haberler:
{haber_metni}

SADECE şu JSON formatını döndür, başka hiçbir şey yazma:
{{
  "skor": <-100 ile +100 arası tam sayı>,
  "kritik": <true/false>,
  "ozet": "<maksimum 2 cümle Türkçe özet, boş olabilir>",
  "haberler_turkce": [
    {{"orijinal": "<orijinal başlık>", "turkce": "<kim, nerede, ne oldu — tek cümle Türkçe>"}},
    ...
  ]
}}

Kural: +100 = güçlü yükseliş baskısı, -100 = güçlü düşüş baskısı, 0 = nötr
Kritik: Fed/merkez bankası, savaş, büyük ekonomik şok = true
haberler_turkce: TÜM haberleri Türkçeye çevir, hiçbirini atlama"""

    try:
        r = _groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=400,
        )
        temiz = r.choices[0].message.content.strip()
        if "```" in temiz:
            temiz = temiz.split("```")[1]
            if temiz.startswith("json"):
                temiz = temiz[4:]
        try:
            baslangic = temiz.index("{")
            bitis = temiz.rindex("}") + 1
            temiz = temiz[baslangic:bitis]
        except ValueError:
            pass
        sonuc = json.loads(temiz.strip())
        skor = max(-100, min(100, int(sonuc.get("skor", 0))))

        turkce_map = {}
        for t in sonuc.get("haberler_turkce", []):
            turkce_map[t.get("orijinal", "")] = t.get("turkce", "")
        for h in haberler:
            h["turkce"] = turkce_map.get(h["title"], h["title"])

        return skor, sonuc
    except Exception as e:
        logger.error(f"LLM haber skoru hatası: {e}")
        return 0, {}

# ─── ANA MODÜL ──────────────────────────────────────────────

def calistir(config):
    try:
        haberler = yeni_haberler_cek()

        if not haberler:
            logger.info("Yeni kritik haber yok.")
            return {
                "modul": "haberler",
                "puan": 50,
                "kritik": False,
                "llm_skor": 0,
                "ozet": "",
                "haber_sayisi": 0,
                "detay": {"durum": "Yeni kritik haber yok"},
            }

        llm_skor, llm_detay = _llm_haber_skoru(haberler)

        # LLM skoru [−100,+100] → modül puanı [0,100]
        # +100 = 90 puan (güçlü al), -100 = 10 puan (sat/bekle)
        modul_puan = 50 + (llm_skor * 0.40)
        modul_puan = max(10, min(90, modul_puan))

        # Tier 1 haber varsa ağırlık artar
        kritik_sayisi = sum(1 for h in haberler if h["tier"] == "kritik")
        if kritik_sayisi >= 2:
            modul_puan = min(90, modul_puan * 1.1)

        kritik = llm_detay.get("kritik", False)
        ozet   = llm_detay.get("ozet", "")

        logger.info(f"Haber modülü: {len(haberler)} haber, "
                    f"llm_skor={llm_skor}, puan={modul_puan:.1f}")

        return {
            "modul": "haberler",
            "puan": round(modul_puan, 1),
            "kritik": kritik,
            "llm_skor": llm_skor,
            "ozet": ozet,
            "haber_sayisi": len(haberler),
            "kritik_sayisi": kritik_sayisi,
            "detay": {
                "llm": f"Haber etkisi skoru: {llm_skor:+d}",
                "ozet": ozet or "Kritik gelişme yok",
                "haberler": haberler,
            },
        }

    except Exception as e:
        logger.error(f"Haber modülü hatası: {e}")
        return {
            "modul": "haberler",
            "puan": 50,
            "kritik": False,
            "llm_skor": 0,
            "ozet": "",
            "detay": {"hata": str(e)},
        }
