from __future__ import annotations

from typing import Any

from ethcompress.compressor import DECOMPRESSOR_ADDRESS, compress_eth_call


def _hex(b: bytes) -> str:
    return "0x" + b.hex()


class FakeProvider:
    def __init__(self, *, fail_compressed: bool = False, want_error: bool = False):
        self.fail_compressed = fail_compressed
        self.want_error = want_error
        self.calls: list[dict[str, Any]] = []

    def make_request(self, method: str, params: list) -> dict[str, Any]:
        self.calls.append({"method": method, "params": params})
        assert method == "eth_call"
        tx = params[0]
        override = params[2] if len(params) >= 3 else None
        is_compressed = tx.get("to") == DECOMPRESSOR_ADDRESS and override is not None
        if is_compressed:
            if self.fail_compressed:
                if self.want_error:
                    return {"error": {"code": -1, "message": "fail compressed"}}
                raise RuntimeError("simulated compressed failure")
            return {"result": "0x1234"}
        # vanilla path
        return {"result": "0xabcd"}


class W3:
    def __init__(self, provider):
        self.provider = provider


def test_execute_compressed_success_cd():
    # Many zeros -> CD should compress and be beneficial
    data = b"\x00" * 1200
    to = "0x000000000000000000000000000000000000dEaD"
    cc = compress_eth_call(to, _hex(data), alg="cd", min_size=800)
    # Sanity: selected CD
    assert cc.algo in ("cd", "vanilla")
    # Execute with a provider that succeeds on compressed
    w3 = W3(FakeProvider())
    out = cc.execute(w3)
    assert out == "0x1234"
    # Ensure a third param (override) was passed
    last = w3.provider.calls[-1]
    assert len(last["params"]) >= 3
    assert last["params"][0]["to"] == DECOMPRESSOR_ADDRESS


def test_execute_compressed_failure_then_fallback():
    # Pattern compressible by FLZ
    data = b"ABCD" * 512
    to = "0x000000000000000000000000000000000000dEaD"
    cc = compress_eth_call(to, _hex(data), alg="flz", min_size=800, allow_fallback=True)
    w3 = W3(FakeProvider(fail_compressed=True))
    out = cc.execute(w3)
    # Should return vanilla result
    assert out == "0xabcd"
    # Expect two calls: one compressed (failed), one vanilla
    assert len(w3.provider.calls) >= 2
    assert w3.provider.calls[0]["params"][0]["to"] == DECOMPRESSOR_ADDRESS
    assert w3.provider.calls[-1]["params"][0]["to"] != DECOMPRESSOR_ADDRESS


def test_execute_compressed_failure_no_fallback_raises():
    data = b"ABCD" * 512
    to = "0x000000000000000000000000000000000000dEaD"
    cc = compress_eth_call(to, _hex(data), alg="flz", min_size=800, allow_fallback=False)
    w3 = W3(FakeProvider(fail_compressed=True, want_error=True))
    raised = False
    try:
        _ = cc.execute(w3)
    except RuntimeError:
        raised = True
    assert raised
