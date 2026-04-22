import logging
import asyncio
import json
import os
import threading
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from core.signal_engine import sinyal_uret, durum_analizi_calistir, build_hedef_mesaji
from filters.calendar import kilit_koy
from output.api import flask_baslat
import config as cfg

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

TR             = timezone(timedelta(hours=3))
POZISYON_DOSYA = "aktif_pozisyon.json"
PERFORMANS_DOSYA = "performans.json"
LOG_DOSYA      = "sinyal_log.json"

# ─── YARDIMCI ───────────────────────────────────────────────

def hafta_sonu_mu():
    return datetime.now(timezone.utc).weekday() >= 5

def config_dict():
    return {
        k: getattr(cfg, k)
        for k in dir(cfg)
        if not k.startswith('_') and
        isinstance(getattr(cfg, k), (int, float, str, list, dict))
    }

def pozisyon_kaydet(giris_tl, hedef_tl, stop_tl, mesaj_id, kurul_gorusu):
    with open(POZISYON_DOSYA, "w") as f:
        json.dump({
            "giris_tl": giris_tl,
            "hedef_tl": hedef_tl,
            "stop_tl":  stop_tl,
            "mesaj_id": mesaj_id,
            "kurul_gorusu": kurul_gorusu,
            "tarih": datetime.now(TR).strftime("%Y-%m-%d %H:%M"),
        }, f)

def pozisyon_sil():
    if os.path.exists(POZISYON_DOSYA):
        os.remove(POZISYON_DOSYA)

def pozisyon_oku():
    if os.path.exists(POZISYON_DOSYA):
        with open(POZISYON_DOSYA) as f:
            return json.load(f)
    return None

def sinyal_logla(tip, giris_tl, cikis_tl=None, kar_yuzde=None,
                 giris_tarihi=None,
                 hedef_tl=None, stop_tl=None, kurul_gorusu=None):
    log = []
    if os.path.exists(LOG_DOSYA):
        with open(LOG_DOSYA) as f:
            log = json.load(f)
    if giris_tarihi is None and tip == "ALIM":
        giris_tarihi = datetime.now(TR).strftime("%Y-%m-%d %H:%M")
    log.append({
        "tip": tip,
        "tarih": datetime.now(TR).strftime("%Y-%m-%d %H:%M"),
        "giris_tarihi": giris_tarihi,
        "giris_tl": giris_tl,
        "cikis_tl": cikis_tl,
        "hedef_tl": hedef_tl,
        "stop_tl": stop_tl,
        "kar_yuzde": kar_yuzde,
        "kurul_gorusu": kurul_gorusu,
    })
    with open(LOG_DOSYA, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

def performans_guncelle(kar_yuzde):
    veri = {"toplam_kar": 0.0, "islem": 0,
            "baslangic": datetime.now(TR).strftime("%d.%m.%Y"),
            "bildirim": False}
    if os.path.exists(PERFORMANS_DOSYA):
        with open(PERFORMANS_DOSYA) as f:
            veri = json.load(f)
    veri["toplam_kar"] += kar_yuzde
    veri["islem"] += 1
    veri["bildirim"] = False
    with open(PERFORMANS_DOSYA, "w") as f:
        json.dump(veri, f)
    return veri

def log_ozeti():
    if not os.path.exists(LOG_DOSYA):
        return None
    with open(LOG_DOSYA) as f:
        log = json.load(f)
    satislar = [k for k in log if k["tip"] == "SATIS" and k.get("kar_yuzde")]
    if not satislar:
        return None
    karlar = [s["kar_yuzde"] for s in satislar]
    return {
        "toplam": len(satislar),
        "winrate": len([k for k in karlar if k > 0]) / len(karlar) * 100,
        "ort_kar": sum(karlar) / len(karlar),
        "toplam_kar": sum(karlar),
    }

# ─── SCHEDULER JOBLAR ───────────────────────────────────────

async def sabah_mesaji_job():
    if hafta_sonu_mu():
        return
    try:
        bot = Bot(token=cfg.TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=cfg.TELEGRAM_GROUP_ID,
            text=(
                "Bismillahirrahmanirrahim. Hayırlı sabahlar. "
                "Allah'ın rahmeti ve bereketi daimi üzerimize olsun; "
                "helalinden bol kazançlar yağdırsın. Hazırsanız başlıyoruz."
            )
        )
    except Exception as e:
        logger.error(f"Sabah mesajı: {e}")

async def piyasa_acilis_job(piyasa_ismi):
    if hafta_sonu_mu():
        return
    try:
        bot = Bot(token=cfg.TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=cfg.TELEGRAM_GROUP_ID,
            text=f"🔔 {piyasa_ismi} piyasasının açılmasına son 5 dakika."
        )
    except Exception as e:
        logger.error(f"Piyasa açılış: {e}")

async def volatilite_baslangic_job():
    if hafta_sonu_mu():
        return
    try:
        # COMEX açılışı öncesi sinyal kilidi
        kilit_koy(cfg.OLAY_ONCESI_DAKIKA // 4,
                  "COMEX volatilite penceresi başlıyor")
        bot = Bot(token=cfg.TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=cfg.TELEGRAM_GROUP_ID,
            text="⚡ Dikkat: Gümüşteki dalgalanmalar 10 dakika içinde artacak."
        )
    except Exception as e:
        logger.error(f"Volatilite başlangıç: {e}")

async def volatilite_bitis_job():
    if hafta_sonu_mu():
        return
    try:
        bot = Bot(token=cfg.TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=cfg.TELEGRAM_GROUP_ID,
            text="📉 Dikkat: Gümüşteki dalgalanmalar 10 dakika içinde sona erecek."
        )
    except Exception as e:
        logger.error(f"Volatilite bitiş: {e}")

async def piyasa_analizi_job():
    if hafta_sonu_mu():
        return
    try:
        logger.info("Periyodik analiz başlıyor...")
        conf = config_dict()
        sinyal_var, mesaj, fiyat_tl, tp_tl, sinyal_tipi = sinyal_uret(conf)
        bot = Bot(token=cfg.TELEGRAM_TOKEN)

        if sinyal_var and mesaj and not pozisyon_oku():
            # Stop hesabı
            from modules.risk import hesapla_stop_tp
            from core.data_engine import get_silver_price_tl
            _, usd_try = get_silver_price_tl()
            from core.signal_engine import tam_analiz_calistir
            analiz = tam_analiz_calistir(conf)
            atr = (analiz.get("modul_sonuclari", {})
                   .get("teknik", {}).get("atr_1h"))
            tp_tl2, sl_tl = hesapla_stop_tp(fiyat_tl, atr, usd_try, conf)
            kurul_g = analiz.get("oylama", {}).get("kurul_gorusu", 0)

            gonderilen = await bot.send_message(
                chat_id=cfg.TELEGRAM_GROUP_ID,
                text=mesaj,
                parse_mode="Markdown"
            )
            pozisyon_kaydet(fiyat_tl, tp_tl or tp_tl2, sl_tl,
                            gonderilen.message_id, kurul_g)
            sinyal_logla("ALIM", giris_tl=fiyat_tl,
                         hedef_tl=tp_tl, stop_tl=sl_tl,
                         kurul_gorusu=kurul_g)
            logger.info(f"Sinyal gönderildi: {sinyal_tipi}")

        elif mesaj and not sinyal_var:
            # Durum özeti
            durum = durum_analizi_calistir(conf)
            await bot.send_message(
                chat_id=cfg.TELEGRAM_GROUP_ID,
                text=durum
            )

    except Exception as e:
        logger.error(f"Piyasa analizi: {e}")

async def fiyat_takip_job():
    try:
        pozisyon = pozisyon_oku()
        if not pozisyon:
            return
        from core.data_engine import get_silver_price_tl
        price_tl, _ = get_silver_price_tl()
        if not price_tl:
            return

        giris_tl = pozisyon["giris_tl"]
        hedef_tl = pozisyon["hedef_tl"]
        mesaj_id = pozisyon["mesaj_id"]
        giris_tarihi = pozisyon.get("tarih")
        kar_yuzde = ((price_tl - giris_tl) / giris_tl) * 100

        logger.info(f"Pozisyon: ₺{giris_tl:.2f} → ₺{price_tl:.2f} (%{kar_yuzde:.2f})")

        bot = Bot(token=cfg.TELEGRAM_TOKEN)

        # Hedef vuruldu
        if price_tl >= hedef_tl:
            conf = config_dict()
            mesaj, net_kar = build_hedef_mesaji(giris_tarihi, giris_tl, price_tl, conf)
            await bot.send_message(
                chat_id=cfg.TELEGRAM_GROUP_ID,
                text=mesaj,
                reply_to_message_id=mesaj_id,
                parse_mode="Markdown"
            )
            sinyal_logla("SATIS", giris_tl=giris_tl,
                         cikis_tl=price_tl, kar_yuzde=net_kar,
                         giris_tarihi=giris_tarihi)
            perf = performans_guncelle(net_kar)
            if (perf["toplam_kar"] >= cfg.KUMULATIF_BILDIRIM_ESIGI
                    and not perf["bildirim"]):
                await bot.send_message(
                    chat_id=cfg.TELEGRAM_GROUP_ID,
                    text=(f"📈 {perf['baslangic']} tarihinden itibaren "
                          f"%{perf['toplam_kar']:.1f} kümülatif kâr.")
                )
                perf["bildirim"] = True
                with open(PERFORMANS_DOSYA, "w") as f:
                    json.dump(perf, f)
            pozisyon_sil()

    except Exception as e:
        logger.error(f"Fiyat takip: {e}")

# ─── TELEGRAM KOMUTLAR ──────────────────────────────────────

async def handle_updates():
    offset = None
    bot = Bot(token=cfg.TELEGRAM_TOKEN)
    while True:
        try:
            updates = await bot.get_updates(offset=offset, timeout=10)
            for upd in updates:
                offset = upd.update_id + 1
                if not (upd.message and upd.message.text):
                    continue
                cmd = upd.message.text.strip()
                chat = upd.message.chat_id

                if cmd == "/log":
                    ozet = log_ozeti()
                    if ozet:
                        metin = (
                            f"📊 Performans\n\n"
                            f"İşlem: {ozet['toplam']}\n"
                            f"Winrate: %{ozet['winrate']:.1f}\n"
                            f"Ort. kâr: %{ozet['ort_kar']:.2f}\n"
                            f"Toplam: %{ozet['toplam_kar']:.1f}"
                        )
                    else:
                        metin = "Henüz tamamlanmış işlem yok."
                    await bot.send_message(chat_id=chat, text=metin)

                elif cmd == "/durum":
                    conf = config_dict()
                    durum = durum_analizi_calistir(conf)
                    await bot.send_message(chat_id=chat, text=durum)

                elif cmd == "/pozisyon":
                    pos = pozisyon_oku()
                    if pos:
                        from core.data_engine import get_silver_price_tl
                        fiyat, _ = get_silver_price_tl()
                        kar = ((fiyat - pos["giris_tl"]) / pos["giris_tl"] * 100
                               if fiyat else 0)
                        metin = (
                            f"📍 Aktif Pozisyon\n\n"
                            f"Giriş: ₺{pos['giris_tl']:.2f}\n"
                            f"Hedef: ₺{pos['hedef_tl']:.2f}\n"
                            f"Stop:  ₺{pos.get('stop_tl', '?')}\n"
                            f"Şu an: ₺{fiyat:.2f if fiyat else '?'}\n"
                            f"Kâr:   %{kar:.1f}\n"
                            f"Kurul: %{pos.get('kurul_gorusu', '?')}"
                        )
                    else:
                        metin = "Açık pozisyon yok."
                    await bot.send_message(chat_id=chat, text=metin)

        except Exception as e:
            logger.error(f"Update handler: {e}")
        await asyncio.sleep(10)

# ─── ANA ────────────────────────────────────────────────────

async def main():
    logger.info("Mars Finance v2.0 başlatılıyor...")

    # Flask API ayrı thread'de
    flask_thread = threading.Thread(target=flask_baslat, daemon=True)
    flask_thread.start()
    logger.info("Dashboard: http://0.0.0.0:5000")

    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    # Sabah mesajı
    scheduler.add_job(sabah_mesaji_job, "cron",
                      hour=cfg.SABAH_MESAJI_SAAT,
                      minute=cfg.SABAH_MESAJI_DAKIKA)

    # Periyodik analiz
    for saat in cfg.ANALIZ_SAATLERI_UTC:
        scheduler.add_job(piyasa_analizi_job, "cron",
                          hour=saat, minute=0)

    # Piyasa açılışları
    for p in cfg.PIYASA_ACILIS:
        scheduler.add_job(piyasa_acilis_job, "cron",
                          hour=p["hour"], minute=p["minute"],
                          kwargs={"piyasa_ismi": p["isim"]})

    # Volatilite
    scheduler.add_job(volatilite_baslangic_job, "cron",
                      hour=cfg.VOLATILITE_BASLANGIC_HOUR,
                      minute=cfg.VOLATILITE_BASLANGIC_MINUTE)
    scheduler.add_job(volatilite_bitis_job, "cron",
                      hour=cfg.VOLATILITE_BITIS_HOUR,
                      minute=cfg.VOLATILITE_BITIS_MINUTE)

    # Fiyat takibi
    scheduler.add_job(fiyat_takip_job, "interval",
                      minutes=cfg.FIYAT_TAKIP_INTERVAL_DAKIKA)

    scheduler.start()
    logger.info("Scheduler aktif.")

    asyncio.create_task(handle_updates())

    # Başlangıçta bir analiz çalıştır
    await piyasa_analizi_job()

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
