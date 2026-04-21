import logging
import pandas as pd
import numpy as np
from core.data_engine import get_silver_data

logger = logging.getLogger(__name__)

def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def _macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig  = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig, macd - sig

def _sma(series, period):
    return series.rolling(window=period).mean()

def _atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def _bollinger(close, period=20, std=2):
    mid   = _sma(close, period)
    sigma = close.rolling(period).std()
    upper = mid + std * sigma
    lower = mid - std * sigma
    return upper, mid, lower, (upper - lower) / mid

def _hesapla(df):
    if len(df) < 50:
        raise ValueError("Yetersiz veri")
    close  = df["Close"].squeeze()
    high   = df["High"].squeeze()
    low    = df["Low"].squeeze()
    volume = df["Volume"].squeeze()
    df = df.copy()
    df["RSI"] = _rsi(close)
    df["MACD"], df["MACD_SIG"], df["MACD_HIST"] = _macd(close)
    df["MA20"]  = _sma(close, 20)
    df["MA50"]  = _sma(close, 50)
    df["MA200"] = _sma(close, 200)
    df["ATR"]   = _atr(high, low, close)
    df["VOL_MA20"] = _sma(volume, 20)
    df["BB_UPPER"], df["BB_MID"], df["BB_LOWER"], df["BB_WIDTH"] = _bollinger(close)
    return df.dropna()

def _sinyal_puan(df, config):
    latest = df.iloc[-1]
    prev   = df.iloc[-2]
    prev2  = df.iloc[-3] if len(df) >= 3 else prev
    rsi_oversold   = config.get("RSI_OVERSOLD", 35)
    rsi_overbought = config.get("RSI_OVERBOUGHT", 68)
    puan = 0
    detay = {}

    rsi_donus = prev["RSI"] < rsi_oversold and latest["RSI"] >= rsi_oversold
    if rsi_donus:
        puan += 25; detay["rsi"] = f"RSI dip dönüşü ({latest['RSI']:.1f})"
    elif latest["RSI"] < rsi_oversold:
        puan += 10; detay["rsi"] = f"RSI aşırı satım ({latest['RSI']:.1f})"
    elif latest["RSI"] > rsi_overbought:
        puan -= 20; detay["rsi"] = f"RSI aşırı alım ({latest['RSI']:.1f})"
    else:
        detay["rsi"] = f"RSI nötr ({latest['RSI']:.1f})"

    macd_cross = (prev2["MACD_HIST"] < 0 and prev["MACD_HIST"] >= 0
                  and latest["MACD_HIST"] > prev["MACD_HIST"])
    if macd_cross:
        puan += 25; detay["macd"] = "MACD yukarı kesişim"
    elif latest["MACD_HIST"] > 0 and latest["MACD_HIST"] > prev["MACD_HIST"]:
        puan += 10; detay["macd"] = "MACD pozitif momentum"
    elif latest["MACD_HIST"] < 0 and latest["MACD_HIST"] < prev["MACD_HIST"]:
        puan -= 15; detay["macd"] = "MACD negatif momentum"
    else:
        detay["macd"] = "MACD nötr"

    ma50_yukseliyor = latest["MA50"] > prev["MA50"] and prev["MA50"] > prev2["MA50"]
    if ma50_yukseliyor:
        puan += 20; detay["ma50"] = "MA50 yukarı eğimli"
    elif latest["MA50"] < prev["MA50"]:
        puan -= 15; detay["ma50"] = "MA50 aşağı eğimli"
    else:
        detay["ma50"] = "MA50 yatay"

    if latest["Close"] > latest["MA50"] > latest["MA200"]:
        puan += 15; detay["ma_pozisyon"] = "Fiyat MA50 ve MA200 üzerinde"
    elif latest["Close"] < latest["MA50"] < latest["MA200"]:
        puan -= 15; detay["ma_pozisyon"] = "Fiyat MA50 ve MA200 altında"
    else:
        detay["ma_pozisyon"] = "MA pozisyonu karma"

    if latest["BB_WIDTH"] < df["BB_WIDTH"].quantile(0.2):
        puan += 10; detay["bollinger"] = "Bollinger sıkışması"
    else:
        detay["bollinger"] = "Bollinger normal"

    if latest["Volume"] >= latest["VOL_MA20"] * 0.8:
        puan += 5; detay["hacim"] = "Hacim yeterli"
    else:
        puan -= 5; detay["hacim"] = "Hacim yetersiz"

    return max(0, min(100, puan)), detay, latest

def calistir(config):
    sonuclar = {}
    agirliklar = {"1h": 0.30, "4h": 0.35, "1d": 0.35}
    periyotlar  = {"1h": "60d", "4h": "180d", "1d": "365d"}
    for interval, agirlik in agirliklar.items():
        try:
            df = get_silver_data(interval=interval, period=periyotlar[interval])
            df_h = _hesapla(df)
            puan, detay, latest = _sinyal_puan(df_h, config)
            sonuclar[interval] = {
                "puan": puan, "detay": detay,
                "fiyat": float(latest["Close"]),
                "atr": float(latest["ATR"]),
                "rsi": float(latest["RSI"]),
            }
        except Exception as e:
            logger.error(f"Teknik [{interval}]: {e}")
            sonuclar[interval] = {"puan": 50, "detay": {}, "fiyat": None, "atr": None, "rsi": None}

    toplam = sum(sonuclar[i]["puan"] * agirliklar[i] for i in agirliklar)
    puanlar = [sonuclar[i]["puan"] for i in agirliklar]
    if all(p >= 60 for p in puanlar): toplam = min(100, toplam + 10)
    elif all(p <= 40 for p in puanlar): toplam = max(0, toplam - 10)

    return {
        "modul": "teknik",
        "puan": round(toplam, 1),
        "detay": sonuclar,
        "fiyat_usd": sonuclar["1h"].get("fiyat"),
        "atr_1h": sonuclar["1h"].get("atr"),
    }
