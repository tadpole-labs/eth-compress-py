from __future__ import annotations

from typing import Any

from ethcompress.middleware import DECOMPRESSOR_ADDRESS, CompressionMiddleware


def _hex_zero_bytes(n: int) -> str:
    return "0x" + ("00" * n)


class FakeProvider:
    def __init__(self, *, fail_compressed: bool = False):
        self.fail_compressed = fail_compressed
        self.calls: list[dict[str, Any]] = []

    def make_request(self, method: str, params: list) -> dict[str, Any]:
        self.calls.append({"method": method, "params": params})
        assert method == "eth_call"
        tx = params[0]
        override = params[2] if len(params) >= 3 else None
        is_compressed = tx.get("to") == DECOMPRESSOR_ADDRESS and override is not None
        if is_compressed:
            if self.fail_compressed:
                return {"error": {"code": -32000, "message": "simulated error"}}
            return {"result": "0x1234"}
        return {"result": "0xabcd"}


class W3:
    def __init__(self, provider):
        self.provider = provider


def test_middleware_compresses_success_returns_compressed_result():
    # Build middleware which will compress via CD deterministically
    mw = CompressionMiddleware(alg="cd", min_size=800, allow_fallback=True)

    prov = FakeProvider()
    w3 = W3(prov)

    def base_make_request(method, params):
        return prov.make_request(method, params)

    middleware = mw(base_make_request, w3)

    # Large zero payload to exceed min_size threshold
    tx = {"to": "0x000000000000000000000000000000000000dEaD", "data": _hex_zero_bytes(1600)}
    res = middleware("eth_call", [tx, "latest"])

    assert res == {"result": "0x1234"}
    # Ensure last call was compressed with override present
    last = prov.calls[-1]
    assert last["params"][0]["to"] == DECOMPRESSOR_ADDRESS
    assert isinstance(last["params"][2], dict)
    assert DECOMPRESSOR_ADDRESS.lower() in last["params"][2]


def test_middleware_fallback_on_error():
    mw = CompressionMiddleware(alg="cd", min_size=800, allow_fallback=True)
    prov = FakeProvider(fail_compressed=True)
    w3 = W3(prov)

    def base_make_request(method, params):
        return prov.make_request(method, params)

    middleware = mw(base_make_request, w3)

    tx = {"to": "0x000000000000000000000000000000000000dEaD", "data": _hex_zero_bytes(1600)}
    res = middleware("eth_call", [tx, "latest"])

    # Should fall back to original call result
    assert res == {"result": "0xabcd"}
    # Expect two calls: compressed then vanilla
    assert len(prov.calls) >= 2
    assert prov.calls[0]["params"][0]["to"] == DECOMPRESSOR_ADDRESS
    assert prov.calls[-1]["params"][0]["to"] != DECOMPRESSOR_ADDRESS


def test_middleware_merges_existing_override():
    mw = CompressionMiddleware(alg="cd", min_size=0, allow_fallback=True)
    prov = FakeProvider()
    w3 = W3(prov)

    def base_make_request(method, params):
        return prov.make_request(method, params)

    middleware = mw(base_make_request, w3)

    # Use a sufficiently large payload so compression triggers and merges overrides
    tx = {"to": "0x000000000000000000000000000000000000dEaD", "data": _hex_zero_bytes(1600)}
    existing = {"0x0000000000000000000000000000000000000002": {"code": "0x5f5ff3"}}
    _ = middleware("eth_call", [tx, "latest", existing])

    last = prov.calls[-1]
    merged = last["params"][2]
    assert (
        DECOMPRESSOR_ADDRESS.lower() in merged
        and "0x0000000000000000000000000000000000000002" in merged
    )
