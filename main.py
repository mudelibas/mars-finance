import fcntl
import logging
import asyncio
import os
import sys
import threading
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from core.data_engine import get_silver_price_dunyakatilim
from core.signal_engine import sinyal_uret
from core import position_store as pstore
from filters.calendar import kilit_kontrol
from output.api import flask_baslat
import config as cfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_TELEGRAM_LOCK_FP = None


def _acquire_telegram_process_lock():
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
            "Yalnızca bir çalışan bırakın, Railway'de replika sayısını 1 yapın veya "
            "MARS_DISABLE_TELEGRAM_LOCK=1 ile bu kilidi (geliştirme) kapatın."
        )
        sys.exit(1)
    f.seek(0)
    f.truncate(0)
    f.write(str(os.getpid()))
    f.flush()
    _TELEGRAM_LOCK_FP = f


TR = timezone(timedelta(hours=3))
PIYASA_ARALIK_SANIYE = 60
FIYAT_TAKIP_SANIYE = 30


def hafta_sonu_mu() -> bool:
    return datetime.now(timezone.utc).weekday() >= 5


def config_dict() -> dict:
    return {
        k: getattr(cfg, k)
        for k in dir(cfg)
        if not k.startswith("_")
        and isinstance(getattr(cfg, k), (int, float, str, list, dict))
    }


def _mesaj_yeni_sinyal(giris_tl: float, hedef_tl: float, net_kar_yuzde: float, yon: str) -> str:
    yon_emoji = "📈 AL" if yon == "long" else "📉 SAT"
    if net_kar_yuzde < 2:
        sure = "~26 saat"
    elif net_kar_yuzde < 3:
        sure = "~31 saat"
    elif net_kar_yuzde < 4:
        sure = "~41 saat"
    else:
        sure = "~47 saat"
    return (
        f"🥈 GÜMÜŞ SİNYALİ — {yon_emoji}\n"
        f"Giriş: ₺{giris_tl:.2f}\n"
        f"Tahmini hedef: ₺{hedef_tl:.2f} (%{net_kar_yuzde:.2f})\n"
        f"Tahmini süre: {sure}"
    )


async def piyasa_analizi_job():
    if hafta_sonu_mu():
        logger.info("Hafta sonu — sinyal yok.")
        return
    try:
        conf = config_dict()
        kilit, kilit_ned = kilit_kontrol()
        if kilit:
            logger.info("Sinyal kilidi: %s", kilit_ned)
            return
        d = sinyal_uret(conf)
        logger.info("Sinyal sonucu: %s", d)
        if not d.get("sinyal"):
            logger.info("Sinyal yok: %s", d.get("red_neden", "neden belirtilmedi"))
            return
        g_tl = d.get("giris_tl")
        h_tl = d.get("hedef_tl")
        netp = float(d.get("net_kar_yuzde") or 0.0)
        skr = int(d.get("skor") or 100)
        yon = d.get("yon") or "long"
        sure = int(d.get("tahmini_sure_saat") or 28)
        if g_tl is None or h_tl is None or float(g_tl) <= 0 or float(h_tl) <= 0:
            logger.info("Sinyal verisi eksik (giris/hedef).")
            return
        g_tl = float(g_tl)
        h_tl = float(h_tl)
        if not cfg.TELEGRAM_TOKEN or not cfg.TELEGRAM_GROUP_ID:
            logger.warning("Telegram token/group_id eksik.")
            return
        bot = Bot(token=cfg.TELEGRAM_TOKEN)
        text = _mesaj_yeni_sinyal(g_tl, h_tl, netp, yon)
        gonderilen = await bot.send_message(
            chat_id=cfg.TELEGRAM_GROUP_ID,
            text=text,
        )
        rec = pstore.yeni_alim_ekle(
            yon, gonderilen.message_id, None, g_tl, h_tl,
            tahmini_sure_saat=sure, yon=yon,
        )
        sid = (rec or {}).get("id")
        logger.info("Sinyal açıldı: yon=%s id=%s sure=%ss", yon, sid, sure)
    except Exception as e:
        logger.error("Piyasa analizi hatası: %s", e, exc_info=True)


async def fiyat_takip_job():
    if hafta_sonu_mu():
        return
    try:
        acik = pstore.tüm_acikler()
        if not acik:
            return
        al, sat, _m = get_silver_price_dunyakatilim()
        if al is None or sat is None:
            logger.error("[takip] Dünya Katılım fiyat yok")
            return
        al_f = float(al)
        sat_f = float(sat)
        if not cfg.TELEGRAM_TOKEN or not cfg.TELEGRAM_GROUP_ID:
            return
        bot = Bot(token=cfg.TELEGRAM_TOKEN)
        for s in list(acik):
            mid = s.get("id")
            mes_id = s.get("telegram_message_id")
            h_raw = s.get("hedef_tl")
            g_raw = s.get("giris_tl")
            yon = s.get("yon") or "long"
            if h_raw is None or g_raw is None:
                continue
            h_tl = float(h_raw)
            g_tl = float(g_raw)

            if yon == "long" and al_f >= h_tl - 1e-6:
                cikis = al_f
                pnl = ((cikis - g_tl) / g_tl) * 100.0 if g_tl > 0 else 0.0
                msg = (
                    f"🎯 Hedefe ulaşıldı (AL)\n"
                    f"Giriş: ₺{g_tl:.2f} → Çıkış: ₺{cikis:.2f}\n"
                    f"Kâr: %{pnl:.2f}"
                )
                await bot.send_message(
                    chat_id=cfg.TELEGRAM_GROUP_ID,
                    text=msg,
                    reply_to_message_id=mes_id,
                )
                pstore.sinyal_kapat(mid, 0, "TP", cikis_tl=cikis)

            else:
                logger.info("[takip] id=%s yon=%s al=%.4f sat=%.4f hedef=%.4f",
                            mid, yon, al_f, sat_f, h_tl)
    except Exception as e:
        logger.error("Fiyat takip: %s", e, exc_info=True)


async def _clear_telegram_webhook_once():
    if not cfg.TELEGRAM_TOKEN:
        return
    try:
        await Bot(token=cfg.TELEGRAM_TOKEN).delete_webhook(drop_pending_updates=False)
    except Exception as e:
        logger.error("Telegram delete_webhook: %s", e)


async def main():
    logger.info("Mars Finance başlatılıyor (TL sinyal + 60s döngü)...")
    await _clear_telegram_webhook_once()
    t = threading.Thread(target=flask_baslat, daemon=True)
    t.start()
    logger.info("Dashboard: 0.0.0.0:5000")
    sched = AsyncIOScheduler(timezone=timezone.utc)
    sched.add_job(piyasa_analizi_job, "interval", seconds=PIYASA_ARALIK_SANIYE, id="piyasa")
    sched.add_job(fiyat_takip_job, "interval", seconds=FIYAT_TAKIP_SANIYE, id="takip")
    sched.start()
    await piyasa_analizi_job()
    while True:
        await asyncio.sleep(600)


if __name__ == "__main__":
    _acquire_telegram_process_lock()
    asyncio.run(main())