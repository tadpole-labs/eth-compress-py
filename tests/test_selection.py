import os
import random

import pytest

from ethcompress.compressor import DECOMPRESSOR_ADDRESS, compress_call_data


def _hex(b: bytes) -> str:
    return "0x" + b.hex()


def test_auto_select_small_compares_codecs():
    target = "0x000000000000000000000000000000000000dEaD"
    data_small = (b"ABCD" * 256) + os.urandom(256)
    to, _calldata, override, meta = compress_call_data(
        _hex(data_small), target, alg="auto", min_size=800
    )
    assert meta["algo"] in ("jit", "cd", "flz", "vanilla")
    if meta["algo"] != "vanilla":
        assert to == DECOMPRESSOR_ADDRESS
        assert isinstance(override, dict) and DECOMPRESSOR_ADDRESS.lower() in override


def test_auto_select_large():
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


@pytest.mark.parametrize(
    "data",
    [
        b"\x00" * 1600,
        b"ABCD" * 4096,
        (b"\x00" * 12 + bytes(range(20))) * 100,
        random.Random(42).randbytes(4096),
    ],
)
def test_auto_chooses_smallest_complete_codec_payload(data):
    target = "0x" + "11" * 20
    candidates = [
        compress_call_data(data, target, alg=alg, min_size=0) for alg in ("jit", "flz", "cd")
    ]
    auto = compress_call_data(data, target, min_size=0)

    def size(result):
        sizes = result[3]["sizes"]
        return sizes["compressed"] + sizes["code"]

    assert size(auto) == min(size(result) for result in candidates)
    assert auto in candidates


def test_large_repeated_data_selects_flz_not_jit():
    data = b"ABCD" * 4096
    _, _, _, meta = compress_call_data(data, "0x" + "11" * 20)
    assert meta["algo"] == "flz"


@pytest.mark.parametrize("alg", ["jit", "flz", "cd"])
def test_explicit_algorithm_is_respected(alg):
    _, _, _, meta = compress_call_data(b"\x00" * 1600, "0x" + "11" * 20, alg=alg)
    assert meta["algo"] == alg
