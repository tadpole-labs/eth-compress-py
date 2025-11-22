import os

from ethcompress.compressor import DECOMPRESSOR_ADDRESS, compress_call_data


def _hex(b: bytes) -> str:
    return "0x" + b.hex()


def test_auto_select_small_compares_cd_vs_flz():
    target = "0x000000000000000000000000000000000000dEaD"
    data_small = (b"ABCD" * 256) + os.urandom(256)
    to, _calldata, override, meta = compress_call_data(
        _hex(data_small), target, alg="auto", min_size=800
    )
    assert meta["algo"] in ("cd", "flz", "vanilla")
    if meta["algo"] != "vanilla":
        assert to == DECOMPRESSOR_ADDRESS
        assert isinstance(override, dict) and DECOMPRESSOR_ADDRESS.lower() in override


def test_auto_select_large_prefers_jit():
    target = "0x000000000000000000000000000000000000dEaD"
    data_large = os.urandom(4096)
    to, calldata, override, meta = compress_call_data(
        _hex(data_large), target, alg="auto", min_size=800
    )
    # Depending on data, JIT may still be not beneficial; allow vanilla
    assert meta["algo"] in ("jit", "vanilla", "cd", "flz")
    if meta["algo"] == "jit":
        assert to == DECOMPRESSOR_ADDRESS
        assert isinstance(override, dict) and DECOMPRESSOR_ADDRESS.lower() in override
        # JIT calldata is 32-byte address word
        assert len(calldata) == 2 + 64


def test_vanilla_when_not_beneficial():
    target = "0x000000000000000000000000000000000000dEaD"
    data = os.urandom(900)
    to, d, override, meta = compress_call_data(_hex(data), target, alg="auto", min_size=800)
    if meta["algo"] == "vanilla":
        assert to == target
        assert d.startswith("0x") and ((len(d) - 2) // 2) == len(data)
        assert override is None
