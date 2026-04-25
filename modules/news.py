"""
RSS haber akışı — sadece dashboard tüketimi.
Groq, LLM, puan, skor ve sinyal sistemi yok: yalnızca kaynaklardan çek, en yeni N haberi döndür.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Tuple

import feedparser

from config import RSS_KAYNAKLAR

logger = logging.getLogger(__name__)

TR = timezone(timedelta(hours=3))
_TAG_RE = re.compile(r"<[^>]+>")

# Varsayılan dönen haber adedi
SON_HABER_SAYISI = 10


def _kisa_ozet(summary: str, max_len: int = 400) -> str:
    if not summary:
        return ""
    t = _TAG_RE.sub(" ", str(summary))
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len] + ("…" if len(t) > max_len else "")


def _alan(entry: Any, *isimler: str, default: str = "") -> str:
    for n in isimler:
        if isinstance(entry, dict) and n in entry:
            v = entry.get(n)
            if v is not None and str(v).strip():
                return str(v).strip()
        if hasattr(entry, n):
            v = getattr(entry, n, None)
            if v is not None and str(v).strip():
                return str(v).strip()
    return default


def _zaman_tuple(entry: Any) -> Optional[Tuple[Any, ...]]:
    for k in ("published_parsed", "updated_parsed"):
        if isinstance(entry, dict) and k in entry:
            t = entry.get(k)
            if t:
                return t
        t = getattr(entry, k, None)
        if t:
            return t
    return None


def _girdi_id(entry: Any) -> str:
    s = f"{_alan(entry, 'title', default='')}{_alan(entry, 'link', default='')}"
    return hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _girdi_zaman(entry: Any) -> str:
    t = _zaman_tuple(entry)
    return _parse_tuple_to_tr_time(t)


def _parse_tuple_to_tr_time(t) -> str:
    if t:
        try:
            utc = datetime(*t[:6], tzinfo=timezone.utc)
            return utc.astimezone(TR).strftime("%H:%M")
        except (TypeError, ValueError) as e:
            logger.debug("Haber zamanı parse: %s", e)
    return datetime.now(TR).strftime("%H:%M")


def _girdi_utc(entry: Any) -> Optional[datetime]:
    t = _zaman_tuple(entry)
    if not t:
        return None
    try:
        return datetime(*t[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _rss_satiri_olustur(
    entry: Any,
    kategori: str,
) -> Optional[dict[str, Any]]:
    title = _alan(entry, "title")
    link = _alan(entry, "link")
    if not title and not link:
        return None
    raw = _alan(entry, "summary", "description")
    eid = _girdi_id(entry)
    return {
        "id": eid,
        "tier": kategori,
        "title": title or "(başlıksız)",
        "link": link,
        "ozet": _kisa_ozet(raw),
        "zaman": _girdi_zaman(entry),
        "_ts": _girdi_utc(entry) or datetime.min.replace(tzinfo=timezone.utc),
    }


def _tum_kayitlari_topla() -> list[dict[str, Any]]:
    """Tüm RSS kaynaklarındaki tüm maddeleri topla (kategori = RSS sözlük anahtarı)."""
    out: list[dict[str, Any]] = []
    for kategori, url_liste in (RSS_KAYNAKLAR or {}).items():
        for url in url_liste or []:
            url = (url or "").strip()
            if not url:
                continue
            try:
                feed = feedparser.parse(url)
                for entry in getattr(feed, "entries", []) or []:
                    if entry is None:
                        continue
                    d = _rss_satiri_olustur(entry, str(kategori))
                    if d:
                        out.append(d)
            except Exception as e:
                logger.warning("RSS hatası (%s): %s", url, e)
    return out


def _sirala_ve_tekillestir(kayitlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kayitlar.sort(key=lambda r: r["_ts"], reverse=True)
    g = []
    gord = set()
    for r in kayitlar:
        eid = r.get("id")
        if eid in gord:
            continue
        gord.add(eid)
        r = dict(r)
        r.pop("_ts", None)
        g.append(r)
    return g


def son_haberler(limit: int = SON_HABER_SAYISI) -> list[dict[str, Any]]:
    """
    RSS'den tüm `RSS_KAYNAKLAR` uçlarını tara, birleştirip en yenilerden
    itibaren `limit` adet listele. Sadece okuma; dosya, oylama veya sinyal yok.
    """
    n = max(1, min(int(limit), 50))
    toplu = _tum_kayitlari_topla()
    siralı = _sirala_ve_tekillestir(toplu)
    return siralı[:n]


def haber_listesi() -> list[dict[str, Any]]:
    """Takma ad: son 10 haber (dashboard)."""
    return son_haberler(SON_HABER_SAYISI)
