import json
import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)
TR = timezone(timedelta(hours=3))

DATABASE_URL = os.environ.get("DATABASE_URL")


def _conn():
    return psycopg2.connect(DATABASE_URL)


def _init_db():
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS signals (
                        id TEXT PRIMARY KEY,
                        status TEXT NOT NULL DEFAULT 'OPEN',
                        data JSONB NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sinyal_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
            conn.commit()
    except Exception as e:
        logger.error(f"DB init hatası: {e}")


_init_db()


def yeni_alim_ekle(
    reason_short="",
    telemesaj_id=None,
    meta=None,
    giris_tl=None,
    hedef_tl=None,
    tahmini_sure_saat=None,
    yon: str = "long",
):
    sid = str(uuid.uuid4())[:12]
    now = datetime.now(TR).strftime("%Y-%m-%d %H:%M:%S")
    rec = {
        "id": sid,
        "status": "OPEN",
        "giris_tl": float(giris_tl) if giris_tl is not None else None,
        "hedef_tl": float(hedef_tl) if hedef_tl is not None else None,
        "tahmini_sure_saat": int(tahmini_sure_saat) if tahmini_sure_saat is not None else 28,
        "created": now,
        "reason": reason_short or "",
        "yon": yon,
        "telegram_message_id": telemesaj_id,
        "meta": meta or {},
    }
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO signals (id, status, data) VALUES (%s, %s, %s)",
                    (sid, "OPEN", json.dumps(rec))
                )
            conn.commit()
        logger.info(f"[pozisyon] OPEN sinyal={sid} giris_tl={rec['giris_tl']} hedef={rec['hedef_tl']} sure={rec['tahmini_sure_saat']}s")
        return rec
    except Exception as e:
        logger.error(f"yeni_alim_ekle hatası: {e}")
        return None


def tüm_acikler():
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, status, data FROM signals WHERE status = 'OPEN' ORDER BY created_at")
                rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row["data"])
            d["id"] = row["id"]
            d["status"] = row["status"]
            result.append(d)
        return result
    except Exception as e:
        logger.error(f"tüm_acikler hatası: {e}")
        return []


def sinyal_kapat(
    sinyal_id, cikis_usd: float = 0.0, neden: str = "TP", cikis_tl: Optional[float] = None
):
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, status, data FROM signals WHERE id = %s AND status = 'OPEN'", (sinyal_id,))
                row = cur.fetchone()
                if not row:
                    return None
                s = dict(row["data"])
                s["id"] = row["id"]
                s["status"] = "CLOSED"
                s["closed"] = datetime.now(TR).strftime("%Y-%m-%d %H:%M:%S")
                s["exit_usd"] = float(cikis_usd) if cikis_usd else 0.0
                s["cikis_tl"] = float(cikis_tl) if cikis_tl is not None else None
                s["close_reason"] = neden
                e_tl = s.get("giris_tl")
                if cikis_tl is not None and e_tl and float(e_tl) > 0:
                    s["pnl_gross_pct"] = round((float(cikis_tl) - float(e_tl)) / float(e_tl) * 100, 3)
                cur.execute(
                    "UPDATE signals SET status = 'CLOSED', data = %s WHERE id = %s",
                    (json.dumps(s), sinyal_id)
                )
            conn.commit()
        logger.info(f"[pozisyon] kapatıldı id={sinyal_id} neden={neden}")
        return s
    except Exception as e:
        logger.error(f"sinyal_kapat hatası: {e}")
        return None


def tüm_kayitlar():
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, status, data FROM signals ORDER BY created_at DESC LIMIT 200")
                rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row["data"])
            d["id"] = row["id"]
            d["status"] = row["status"]
            result.append(d)
        return result
    except Exception as e:
        logger.error(f"tüm_kayitlar hatası: {e}")
        return []


def istatistik_ozet():
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, status, data, created_at FROM signals")
                rows = cur.fetchall()
        now = datetime.now(TR)

        açık = [r for r in rows if r["status"] == "OPEN"]
        kapalı = [r for r in rows if r["status"] == "CLOSED"]

        kazançlı = 0
        for r in kapalı:
            p = dict(r["data"]).get("pnl_gross_pct")
            try:
                if p is not None and float(p) > 0:
                    kazançlı += 1
            except Exception:
                pass

        gecici_basarisiz = 0
        for r in açık:
            d = dict(r["data"])
            sure = int(d.get("tahmini_sure_saat") or 28)
            try:
                ts = d.get("created", "")
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TR)
                gecen_saat = (now - dt).total_seconds() / 3600
                if gecen_saat > sure:
                    gecici_basarisiz += 1
            except Exception:
                pass

        n_kap = len(kapalı)
        toplam_deger = kazançlı + gecici_basarisiz
        success_rate_pct = round(100.0 * kazançlı / toplam_deger, 1) if toplam_deger > 0 else None

        sureler = []
        for r in kapalı:
            d = dict(r["data"])
            if d.get("close_reason") != "TP":
                continue
            try:
                created = datetime.strptime(d["created"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TR)
                closed = datetime.strptime(d["closed"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TR)
                sureler.append((closed - created).total_seconds() / 3600)
            except Exception:
                pass
        ort_sure_saat = round(sum(sureler) / len(sureler), 1) if sureler else None

        karlar = []
        for r in kapalı:
            d = dict(r["data"])
            if d.get("close_reason") != "TP":
                continue
            try:
                p = d.get("pnl_gross_pct")
                if p is not None:
                    karlar.append(float(p))
            except Exception:
                pass
        ort_kar_pct = round(sum(karlar) / len(karlar), 2) if karlar else None

        strict_kazanli = 0
        for r in kapalı:
            d = dict(r["data"])
            if d.get("close_reason") != "TP":
                continue
            try:
                sure = int(d.get("tahmini_sure_saat") or 28)
                created = datetime.strptime(d["created"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TR)
                closed = datetime.strptime(d["closed"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TR)
                gecen = (closed - created).total_seconds() / 3600
                if gecen <= sure:
                    strict_kazanli += 1
            except Exception:
                pass
        strict_toplam = strict_kazanli + gecici_basarisiz
        strict_success_rate_pct = round(100.0 * strict_kazanli / strict_toplam, 1) if strict_toplam > 0 else None

        return {
            "active_count": len(açık),
            "closed_count": n_kap,
            "open_older_24h": gecici_basarisiz,
            "wins": kazançlı,
            "success_rate_pct": success_rate_pct,
            "ort_sure_saat": ort_sure_saat,
            "strict_success_rate_pct": strict_success_rate_pct,
            "ort_kar_pct": ort_kar_pct,
        }
    except Exception as e:
        logger.error(f"istatistik_ozet hatası: {e}")
        return {
            "active_count": 0,
            "closed_count": 0,
            "open_older_24h": 0,
            "wins": 0,
            "success_rate_pct": None,
            "ort_sure_saat": None,
            "strict_success_rate_pct": None,
            "ort_kar_pct": None,
        }


def state_oku(key: str) -> Optional[str]:
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM sinyal_state WHERE key = %s", (key,))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as e:
        logger.error(f"state_oku hatası: {e}")
        return None


def state_yaz(key: str, value: str):
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO sinyal_state (key, value, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()
                """, (key, value, value))
            conn.commit()
    except Exception as e:
        logger.error(f"state_yaz hatası: {e}")