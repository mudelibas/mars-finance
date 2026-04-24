import logging
from core.data_engine import get_macro_data, get_market_context, _indir
import config as cfg

logger = logging.getLogger(__name__)

REJIMLER = {
    "risk_on": "Risk-On",
    "risk_off": "Risk-Off",
    "enflasyonist": "Enflasyonist",
    "deflasyonist": "Deflasyonist",
}

T_DXY = "DX-Y.NYB"
T_TNX = "^TNX"


def _gunluk_roc1(ticker, period="10d", interval="1d"):
    """Bir gün kapanış değişimi % (ani hareket tespiti)."""
    df = _indir(ticker, period, interval)
    if df is None or len(df) < 2:
        return 0.0, 0.0, None, None
    c = df["Close"].astype(float)
    a, b = float(c.values[-1]), float(c.values[-2])
    r = (a - b) / b * 100 if b else 0.0
    return r, 0, a, b


def belirle(config):
    """
    DXY + ABD 10Y (TNX) yön ve momentum. Tek seferde aşırı hareket → sinyal bloğu.
    """
    try:
        ctx = get_market_context()
        macro = get_macro_data()

        vix = ctx.get("vix") or 20
        sp500 = ctx.get("sp500_degisim_yuzde") or 0
        faiz_lv = ctx.get("faiz") or 4.0
        fed_rate = macro.get("fed_rate") or 4.0
        cpi = macro.get("cpi") or 3.0

        dxy_roc, _, dxy_son, _ = _gunluk_roc1(T_DXY)
        tnx_roc, _, _, _ = _gunluk_roc1(T_TNX)

        esik_dxy = getattr(cfg, "MAKRO_DXY_ANI_ESIK", 0.5)
        esik_tnx = getattr(cfg, "MAKRO_TNX_ANI_ESIK", 0.3)
        spike_veto = (abs(dxy_roc) >= esik_dxy) or (abs(tnx_roc) >= esik_tnx)
        if spike_veto:
            logger.warning(
                f"[MAKRO] ani hareket veto: dxy_roc%={dxy_roc:.2f} tnx_roc%={tnx_roc:.2f}"
            )

        # Basit hizalama: XAG lehine: DXY hafif düşüş, faiz aşırı zıplamaz
        puan = 50
        if -0.15 <= dxy_roc <= 0.1 and 0.02 <= tnx_roc < esik_tnx * 0.5:
            puan = 72
        elif 0.05 < dxy_roc < 0.25 or tnx_roc < -0.05:
            puan = 60
        elif dxy_roc < -0.1:
            puan = 70
        else:
            puan = 45

        if vix > 32 or (sp500 is not None and sp500 < -2.5):
            puan = max(20, puan - 25)
            rej = "risk_off"
        elif cpi and cpi > 4.0 and (faiz_lv is None or float(faiz_lv) < 4.5):
            rej = "enflasyonist"
        elif (faiz_lv and float(faiz_lv) > 5.0) and (sp500 or 0) < 0:
            rej = "deflasyonist"
        else:
            rej = "risk_on"

        rejim = rej
        puan = float(max(0, min(100, puan)))

        return {
            "modul": "makro",
            "rejim": rejim,
            "rejim_str": REJIMLER.get(rejim, rejim),
            "puan": puan,
            "veto_spike_makro": bool(spike_veto),
            "dxy_roc1_gun": dxy_roc,
            "tnx_roc1_gun": tnx_roc,
            "vix": vix,
            "faiz_tnx": faiz_lv,
            "detay": {
                "DXY_roc": f"Günlük %{dxy_roc:.2f}, sev={dxy_son or '-'}",
                "TNX_roc": f"Günlük %{tnx_roc:.2f}",
                "spike_kural": f"|DXY|>={esik_dxy} veya |TNX|>={esik_tnx} → sinyal yasak",
            },
        }

    except Exception as e:
        logger.error(f"Makro rejim hatası: {e}")
        return {
            "modul": "makro",
            "rejim": "risk_on",
            "rejim_str": "Bilinmiyor",
            "puan": 25,
            "veto_spike_makro": True,
            "dxy_roc1_gun": 0,
            "tnx_roc1_gun": 0,
            "detay": {"hata": str(e)},
        }
