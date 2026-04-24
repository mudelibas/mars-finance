import fcntl
import logging
import asyncio
import json
import os
import sys
import threading
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from core.data_engine import get_silver_price_tl
from core.signal_engine import sinyal_uret, build_hedef_mesaji, tam_analiz_calistir
from filters.calendar import kilit_koy
from output.api import flask_baslat
from modules.risk import hesapla_stop_tp
import config as cfg

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

_TELEGRAM_LOCK_FP = None

def _acquire_telegram_process_lock():
    """Aynı makinede ikinci bir bot sürecini engeller (getUpdates 409)."""
    global _TELEGRAM_LOCK_FP
    if os.environ.get("MARS_DISABLE_TELEGRAM_LOCK", "").lower() in ("1", "true", "yes"):
        return
    path = os.environ.get("MARS_TELEGRAM_LOCK_FILE", "/tmp/mars-finance-telegram.lock")
    f = open(path, "a+", encoding="utf-8")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error(
            "Telegram: başka bir süreç bu kilidi tutuyor (409). "
            "Yalnızca bir çalışan bırakın, Railway’de replika sayısını 1 yapın veya "
            "MARS_DISABLE_TELEGRAM_LOCK=1 ile bu kilidi (geliştirme) kapatın."
        )
        sys.exit(1)
    f.seek(0)
    f.truncate(0)
    f.write(str(os.getpid()))
    f.flush()
    _TELEGRAM_LOCK_FP = f

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

# ─── SCHEDULER JOBLAR ───────────────────────────────────────

async def volatilite_baslangic_job():
    """Sinyal kilidi (metin bildirimsiz)."""
    if hafta_sonu_mu():
        return
    try:
        kilit_koy(cfg.OLAY_ONCESI_DAKIKA // 4,
                  "COMEX volatilite penceresi başlıyor")
    except Exception as e:
        logger.error(f"Volatilite başlangıç kilidi: {e}")

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
            _, usd_try = get_silver_price_tl()
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

    except Exception as e:
        logger.error(f"Piyasa analizi: {e}")

async def fiyat_takip_job():
    try:
        pozisyon = pozisyon_oku()
        if not pozisyon:
            return
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
            performans_guncelle(net_kar)
            pozisyon_sil()

    except Exception as e:
        logger.error(f"Fiyat takip: {e}")

# ─── ANA ────────────────────────────────────────────────────

async def _clear_telegram_webhook_once():
    """Giden mesaj modu; eski webhook getUpdates ile çakışmasın diye temizlenir."""
    if not cfg.TELEGRAM_TOKEN:
        return
    try:
        bot = Bot(token=cfg.TELEGRAM_TOKEN)
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:
        logger.error(f"Telegram delete_webhook: {e}")

async def main():
    logger.info("Mars Finance v2.0 başlatılıyor...")
    await _clear_telegram_webhook_once()

    # Flask API ayrı thread'de
    flask_thread = threading.Thread(target=flask_baslat, daemon=True)
    flask_thread.start()
    logger.info("Dashboard: 0.0.0.0:5000")

    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    # Periyodik analiz
    for saat in cfg.ANALIZ_SAATLERI_UTC:
        scheduler.add_job(piyasa_analizi_job, "cron",
                          hour=saat, minute=0)

    # Volatilite: yalnız kilit (Telegram yok)
    scheduler.add_job(volatilite_baslangic_job, "cron",
                      hour=cfg.VOLATILITE_BASLANGIC_HOUR,
                      minute=cfg.VOLATILITE_BASLANGIC_MINUTE)

    # Fiyat takibi
    scheduler.add_job(fiyat_takip_job, "interval",
                      minutes=cfg.FIYAT_TAKIP_INTERVAL_DAKIKA)

    scheduler.start()
    logger.info("Scheduler aktif.")

    # Başlangıçta bir analiz çalıştır
    await piyasa_analizi_job()

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    _acquire_telegram_process_lock()
    asyncio.run(main())
