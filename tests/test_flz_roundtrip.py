import os
import time

from ethcompress import flz_compress, flz_decompress


def _hex(b: bytes) -> str:
    return "0x" + b.hex()


def test_flz_roundtrip_structured():
    # Structured pattern to give FLZ something to compress
    pat = (b"ABCD" * 64) + (b"\x00" * 128) + (b"EFGH" * 64)
    h = _hex(pat)
    t0 = time.perf_counter()
    comp = flz_compress(h)
    t1 = time.perf_counter()
    decomp = flz_decompress(comp)
    t2 = time.perf_counter()
    assert decomp == h
    print(
        f"FLZ structured: in={len(pat)}B comp={(len(comp)-2)//2}B comp_ms={(t1-t0)*1000:.3f} decomp_ms={(t2-t1)*1000:.3f}"
    )


def test_flz_roundtrip_random_small_medium():
    for n in (64, 1024, 5000):
        data = os.urandom(n)
        h = _hex(data)
        t0 = time.perf_counter()
        comp = flz_compress(h)
        t1 = time.perf_counter()
        decomp = flz_decompress(comp)
        t2 = time.perf_counter()
        assert decomp == h
        print(
            f"FLZ random: n={n} comp={(len(comp)-2)//2}B comp_ms={(t1-t0)*1000:.3f} decomp_ms={(t2-t1)*1000:.3f}"
        )
