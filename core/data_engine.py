import time
import logging
import requests
import yfinance as yf
from datetime import datetime, timezone
from config import STALE_DATA_DAKIKA

logger = logging.getLogger(__name__)
_fiyat_cache = {"alis": None, "satis": None, "zaman": 0}
_altin_cache = {"alis": None, "satis": None, "zaman": 0}
FIYAT_CACHE_SURE = 60

def _dunya_makas(alis, satis):
    """(alis, satis, makas) tuple — makas her zaman float veya None."""
    if alis is not None and satis is not None:
        return round(float(satis) - float(alis), 4)
    return None

# ─── YARDIMCI ───────────────────────────────────────────────

def _indir(ticker, period, interval):
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         auto_adjust=True, progress=False)
        if df.empty:
            return None
        df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        # Stale data kontrolü
        son_zaman = df.index[-1]
        if hasattr(son_zaman, 'tzinfo') and son_zaman.tzinfo is None:
            son_zaman = son_zaman.replace(tzinfo=timezone.utc)
        gecen = (datetime.now(timezone.utc) - son_zaman).total_seconds() / 60
        if gecen > STALE_DATA_DAKIKA and interval in ["5m", "15m"]:
            logger.warning(f"{ticker} verisi {gecen:.0f} dk eski.")
        return df
    except Exception as e:
        logger.error(f"{ticker} indirme hatası: {e}")
        return None

# ─── FİYAT VERİLERİ ─────────────────────────────────────────

def get_silver_data(interval="1h", period="60d"):
    df = _indir("SI=F", period, interval)
    if df is None:
        raise ValueError(f"Gümüş verisi alınamadı ({interval})")
    return df

def get_gold_data(interval="1h", period="60d"):
    df = _indir("GC=F", period, interval)
    if df is None:
        raise ValueError(f"Altın verisi alınamadı ({interval})")
    return df

def get_silver_price_dunyakatilim():
    """Dünya Katılım'dan gümüş alış/satış fiyatını çeker, 60 saniye cache'ler."""
    global _fiyat_cache
    a0, s0 = _fiyat_cache.get("alis"), _fiyat_cache.get("satis")
    if (time.time() - _fiyat_cache["zaman"] < FIYAT_CACHE_SURE
            and a0 is not None and s0 is not None):
        return a0, s0, _dunya_makas(a0, s0)
    try:
        import re
        r = requests.get(
            "https://dunyakatilim.com.tr/gunluk-kurlar",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        r.raise_for_status()
        
        # Gümüş (XAG) satırını bul ve fiyatları çıkar
        match = re.search(
            r'G&#xFC;m&#xFC;&#x15F;\s*\(XAG\).*?</td>.*?<td[^>]*>(\d+[.,]\d+)</td>.*?<td[^>]*>(\d+[.,]\d+)</td>',
            r.text, re.IGNORECASE | re.DOTALL
        )
        
        if match:
            alis = float(match.group(1).replace(",", "."))
            satis = float(match.group(2).replace(",", "."))
            makas = _dunya_makas(alis, satis)
            _fiyat_cache = {"alis": alis, "satis": satis, "zaman": time.time()}
            logger.info(f"Gümüş fiyatı: alış={alis}, satış={satis}, makas={makas}")
            return alis, satis, makas
        else:
            logger.error("Gümüş fiyatı regex eşleşmedi - HTML yapısı değişmiş olabilir")
            return None, None, None
    except Exception as e:
        logger.error(f"Dünya Katılım scraping hatası: {e}")
        a, s = _fiyat_cache.get("alis"), _fiyat_cache.get("satis")
        if a is not None and s is not None:
            return a, s, _dunya_makas(a, s)
        return None, None, None

def get_silver_price_tl():
    try:
        alis, satis, makas = get_silver_price_dunyakatilim()
        if alis and satis:
            orta = (alis + satis) / 2
            usdtry = _indir("USDTRY=X", "1d", "5m")
            usd_try = float(usdtry["Close"].values[-1]) if usdtry is not None else None
            return orta, usd_try
        return None, None
    except Exception as e:
        logger.error(f"TL fiyat hatası: {e}")
        return None, None

def get_gold_price_dunyakatilim():
    """Dünya Katılım'dan altın alış/satış fiyatını çeker, 60 saniye cache'ler."""
    global _altin_cache
    a0, s0 = _altin_cache.get("alis"), _altin_cache.get("satis")
    if (time.time() - _altin_cache["zaman"] < FIYAT_CACHE_SURE
            and a0 is not None and s0 is not None):
        return a0, s0, _dunya_makas(a0, s0)
    try:
        import re
        r = requests.get(
            "https://dunyakatilim.com.tr/gunluk-kurlar",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        r.raise_for_status()
        
        # XAU satırını bul ve fiyatları çıkar
        match = re.search(
            r'Alt&#x131;n\s*\(XAU\).*?</td>.*?<td[^>]*>(\d[.,]\d{3}[.,]\d{4})</td>.*?<td[^>]*>(\d[.,]\d{3}[.,]\d{4})</td>',
            r.text, re.IGNORECASE | re.DOTALL
        )
        
        if match:
            # Handle Turkish number format: 6,756.1019 -> 6756.1019 (remove thousands comma, keep decimal point)
            alis_str = match.group(1).replace(",", "")
            satis_str = match.group(2).replace(",", "")
            alis = float(alis_str)
            satis = float(satis_str)
            makas = _dunya_makas(alis, satis)
            _altin_cache = {"alis": alis, "satis": satis, "zaman": time.time()}
            logger.info(f"Altın fiyatı: alış={alis}, satış={satis}, makas={makas}")
            return alis, satis, makas
        else:
            logger.error("Altın fiyatı regex eşleşmedi - HTML yapısı değişmiş olabilir")
            return None, None, None
    except Exception as e:
        logger.error(f"Dünya Katılım altın scraping hatası: {e}")
        a, s = _altin_cache.get("alis"), _altin_cache.get("satis")
        if a is not None and s is not None:
            return a, s, _dunya_makas(a, s)
        return None, None, None

def get_gold_price_tl():
    try:
        xau = _indir("GC=F", "1d", "5m")
        usdtry = _indir("USDTRY=X", "1d", "5m")
        if xau is None or usdtry is None:
            return None, None
        xau_usd = float(xau["Close"].values[-1])
        usd_try = float(usdtry["Close"].values[-1])
        xau_tl_gram = (xau_usd / 31.1035) * usd_try
        return xau_tl_gram, usd_try
    except Exception as e:
        logger.error(f"Altın TL fiyat hatası: {e}")
        return None, None

# ─── BAĞLAM VERİLERİ ────────────────────────────────────────

def get_market_context():
    ctx = {}
    semboller = {
        "dxy":   ("DX-Y.NYB", "5d", "1d"),
        "altin": ("GC=F",     "5d", "1d"),
        "petrol":("BZ=F",     "5d", "1d"),
        "faiz":  ("^TNX",     "5d", "1d"),
        "sp500": ("^GSPC",    "5d", "1d"),
        "vix":   ("^VIX",     "5d", "1d"),
        "gumus": ("SI=F",     "5d", "1d"),
    }
    for anahtar, (ticker, period, interval) in semboller.items():
        try:
            df = _indir(ticker, period, interval)
            if df is not None and len(df) >= 2:
                vals = df["Close"].values
                ctx[anahtar] = float(vals[-1])
                ctx[f"{anahtar}_degisim"] = float(vals[-1] - vals[-2])
                ctx[f"{anahtar}_degisim_yuzde"] = float(
                    (vals[-1] - vals[-2]) / vals[-2] * 100
                )
            else:
                ctx[anahtar] = None
        except Exception as e:
            logger.error(f"{anahtar} context hatası: {e}")
            ctx[anahtar] = None
    return ctx

# ─── COT VERİSİ ─────────────────────────────────────────────

def get_cot_data():
    try:
        url = "https://www.cftc.gov/dea/newcot/f_disagg.txt"
        response = requests.get(url, timeout=15)
        lines = response.text.strip().split("\n")
        for line in lines:
            if "SILVER" in line.upper():
                parts = line.split(",")
                try:
                    report_date = parts[2].strip().strip('"')
                    comm_long = float(parts[7].strip())
                    comm_short = float(parts[8].strip())
                    noncomm_long = float(parts[13].strip())
                    noncomm_short = float(parts[14].strip())
                    open_interest = float(parts[3].strip())
                    total = comm_long + comm_short
                    short_ratio = (comm_short / total) * 100 if total > 0 else 50
                    net_spekulatif = noncomm_long - noncomm_short
                    return {
                        "short_ratio": short_ratio,
                        "comm_long": comm_long,
                        "comm_short": comm_short,
                        "net_spekulatif": net_spekulatif,
                        "open_interest": open_interest,
                        "tarih": report_date,
                    }
                except Exception as e:
                    logger.error(f"COT satır ayrıştırma: {e}")
        return {"short_ratio": 50, "net_spekulatif": 0,
                "open_interest": 0, "tarih": "bilinmiyor"}
    except Exception as e:
        logger.error(f"COT hatası: {e}")
        return {"short_ratio": 50, "net_spekulatif": 0,
                "open_interest": 0, "tarih": "bilinmiyor"}

# ─── FRED MAKROEKONOMİK VERİ ────────────────────────────────

def get_fred_series(series_id):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        r = requests.get(url, timeout=10)
        lines = r.text.strip().split("\n")
        last = lines[-1].split(",")
        return float(last[1])
    except Exception as e:
        logger.error(f"FRED serisi okunamadı ({series_id}): {e}")
        return None

def get_macro_data():
    return {
        "cpi": get_fred_series("CPIAUCSL"),
        "fed_rate": get_fred_series("FEDFUNDS"),
        "ism": get_fred_series("MANEMP"),
    }

# ─── GOLD/SILVER RATIO ──────────────────────────────────────

def get_gsr():
    try:
        xau = _indir("GC=F", "90d", "1d")
        xag = _indir("SI=F", "90d", "1d")
        if xau is None or xag is None:
            return None, None, None
        gsr_seri = xau["Close"] / xag["Close"]
        gsr_guncel = float(gsr_seri.values[-1])
        gsr_ort = float(gsr_seri.mean())
        gsr_std = float(gsr_seri.std())
        zscore = (gsr_guncel - gsr_ort) / gsr_std if gsr_std > 0 else 0
        return gsr_guncel, gsr_ort, zscore
    except Exception as e:
        logger.error(f"GSR hatası: {e}")
        return None, None, None
