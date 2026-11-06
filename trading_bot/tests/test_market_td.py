import pandas as pd

from paper_signals.market import _drop_weekend, _resample_mt


def frame(start, periods, freq="1h"):
    idx = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 0.0},
                        index=idx)


def test_drop_weekend_removes_flat_fill():
    # Viernes 2026-11-06 20:00 UTC a domingo 2026-11-08 23:00 UTC (EST: NY = UTC-5).
    df = _drop_weekend(frame("2026-11-06 20:00", 52))
    assert df.index.min() == pd.Timestamp("2026-11-06 20:00", tz="UTC")   # 15:00 NY, abierto
    assert pd.Timestamp("2026-11-06 22:00", tz="UTC") not in df.index     # 17:00 NY, cerrado
    assert pd.Timestamp("2026-11-07 12:00", tz="UTC") not in df.index     # sábado
    assert pd.Timestamp("2026-11-08 22:00", tz="UTC") in df.index         # abre domingo 17:00 NY


def test_resample_mt_aligns_to_server_time():
    out = _resample_mt(frame("2026-11-04 22:00", 48), "1d")
    # Día del servidor (UTC+2) empieza a las 22:00 UTC.
    assert list(out.index) == [pd.Timestamp("2026-11-04 22:00", tz="UTC"),
                               pd.Timestamp("2026-11-05 22:00", tz="UTC")]
    h4 = _resample_mt(frame("2026-11-05 00:00", 8), "4h")
    assert h4.index[1] == pd.Timestamp("2026-11-05 02:00", tz="UTC")       # 04:00 servidor
