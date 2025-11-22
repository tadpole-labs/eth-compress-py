import os
import time

from ethcompress import cd_compress, cd_decompress


def _hex(b: bytes) -> str:
    return "0x" + b.hex()


def test_cd_roundtrip_zero_and_ff_runs():
    data = bytes([0x00]) * 200 + bytes([0xFF]) * 64 + bytes([0x00]) * 17
    h = _hex(data)
    t0 = time.perf_counter()
    comp = cd_compress(h)
    t1 = time.perf_counter()
    decomp = cd_decompress(comp)
    t2 = time.perf_counter()
    assert decomp == h
    print(
        f"CD runs: in={len(data)}B comp={(len(comp) - 2) // 2}B comp_ms={(t1 - t0) * 1000:.3f} decomp_ms={(t2 - t1) * 1000:.3f}"
    )


def test_cd_roundtrip_random_small_medium():
    for n in (64, 1024, 5000):
        data = os.urandom(n)
        h = _hex(data)
        t0 = time.perf_counter()
        comp = cd_compress(h)
        t1 = time.perf_counter()
        decomp = cd_decompress(comp)
        t2 = time.perf_counter()
        assert decomp == h
        print(
            f"CD random: n={n} comp={(len(comp) - 2) // 2}B comp_ms={(t1 - t0) * 1000:.3f} decomp_ms={(t2 - t1) * 1000:.3f}"
        )
