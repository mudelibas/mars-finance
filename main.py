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
from core.data_engine import get_silver_price_tl, get_xagusd_spot_last
from core.signal_engine import sinyal_uret, build_kapanis_mesaji_usd, tam_analiz_calistir
from core import position_store as pstore
from filters.calendar import kilit_koy
from output.api import flask_baslat
from modules.risk import fiyat_erkun_esigi
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
                 hedef_tl=None, stop_tl=None, kurul_gorusu=None,
                 entry_usd=None, tp_usd=None, sinyal_id=None):
    log = []
    if os.path.exists(LOG_DOSYA):
        with open(LOG_DOSYA) as f:
            log = json.load(f)
    if giris_tarihi is None and tip == "ALIM":
        giris_tarihi = datetime.now(TR).strftime("%Y-%m-%d %H:%M")
    rec = {
        "tip": tip,
        "tarih": datetime.now(TR).strftime("%Y-%m-%d %H:%M"),
        "giris_tarihi": giris_tarihi,
        "giris_tl": giris_tl,
        "cikis_tl": cikis_tl,
        "hedef_tl": hedef_tl,
        "stop_tl": stop_tl,
        "kar_yuzde": kar_yuzde,
        "kurul_gorusu": kurul_gorusu,
        "entry_usd": entry_usd,
        "tp_usd": tp_usd,
        "signal_id": sinyal_id,
    }
    log.append(rec)
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
        sinyal_var, mesaj, e_usd, t_usd, sinyal_tipi, extra = sinyal_uret(conf)
        bot = Bot(token=cfg.TELEGRAM_TOKEN)
        fiyat_tl, _ = get_silver_price_tl()

        if sinyal_var and mesaj and pstore.acik_sinyal_sayisi() < cfg.SINYAL_MAKS_AKTIF:
            kurul_g = (extra or {}).get("confidence", 0) if extra else 0
            gonderilen = await bot.send_message(
                chat_id=cfg.TELEGRAM_GROUP_ID,
                text=mesaj,
                parse_mode="Markdown"
            )
            rsn = ((extra or {}).get("reason") or "")[:400]
            rec = pstore.yeni_alim_ekle(
                e_usd, t_usd, kurul_g, rsn,
                telemesaj_id=gonderilen.message_id,
            )
            sid = rec.get("id") if rec else None
            sinyal_logla(
                "ALIM", giris_tl=fiyat_tl or 0, hedef_tl=0, stop_tl=None,
                kurul_gorusu=kurul_g,
                entry_usd=e_usd, tp_usd=t_usd, sinyal_id=sid,
            )
            logger.info(f"Scalp sinyal: {sinyal_tipi} id={sid}")

    except Exception as e:
        logger.error(f"Piyasa analizi: {e}")

async def fiyat_takip_job():
    """Açık USD sinyalleri: sadece TP (kâr) ve %80 ilerlemede erken uyarı. Stop yok."""
    try:
        acik = pstore.tüm_acikler()
        if not acik:
            return
        spot = get_xagusd_spot_last()
        if spot is None:
            logger.error("[takip] XAG spot yok")
            return
        conf = config_dict()
        bot = Bot(token=cfg.TELEGRAM_TOKEN)
        fiyat_tl, _ = get_silver_price_tl()

        for s in list(acik):
            entry = s.get("entry_target_usd")
            tpv = s.get("tp_usd")
            if not entry or not tpv or entry <= 0 or tpv <= 0:
                continue
            erken = fiyat_erkun_esigi(entry, tpv, conf)
            mid = s.get("id")
            mes_id = s.get("telegram_message_id")
            if spot < entry:
                continue
            if spot >= float(tpv):
                m, net_br = build_kapanis_mesaji_usd(entry, tpv, spot, conf)
                await bot.send_message(
                    chat_id=cfg.TELEGRAM_GROUP_ID,
                    text=m,
                    reply_to_message_id=mes_id,
                    parse_mode="Markdown"
                )
                sinyal_logla(
                    "SATIS", giris_tl=fiyat_tl or 0, cikis_tl=None,
                    kar_yuzde=net_br, giris_tarihi=s.get("created"),
                    hedef_tl=0, entry_usd=entry, tp_usd=tpv, sinyal_id=mid,
                )
                performans_guncelle(net_br)
                pstore.sinyal_kapat(mid, spot, "TP")
            elif (spot >= float(erken)) and not s.get("early_80_alerts_sent"):
                await bot.send_message(
                    chat_id=cfg.TELEGRAM_GROUP_ID,
                    text=(f"📍 Erken uyar: XAG ~%80 hedefe yakın (spot {spot:.4f}, "
                          f"hedef {float(tpv):.4f})."),
                    reply_to_message_id=mes_id,
                )
                pstore.early_alert_isaretle(mid)
            logger.info(f"[takip] id={mid} entry={entry} spot={spot} erken={erken:.4f} tp={tpv}")

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
