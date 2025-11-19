from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ethcompress.middleware import DECOMPRESSOR_ADDRESS, AsyncCompressionMiddleware


def _hex_zero_bytes(n: int) -> str:
    return "0x" + ("00" * n)


class FakeAsyncProvider:
    def __init__(self, *, fail_compressed: bool = False):
        self.fail_compressed = fail_compressed
        self.calls: list[dict[str, Any]] = []

    async def make_request(self, method: str, params: list) -> dict[str, Any]:
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


class AW3:
    def __init__(self, provider):
        self.provider = provider


@pytest.mark.parametrize("fail", [False, True])
def test_async_middleware_compressed_and_fallback(fail: bool) -> None:
    mw = AsyncCompressionMiddleware(alg="cd", min_size=800, allow_fallback=True)
    prov = FakeAsyncProvider(fail_compressed=fail)
    w3 = AW3(prov)

    async def make_request(method, params):
        return await prov.make_request(method, params)

    middleware = mw(make_request, w3)

    async def run_case():
        tx = {"to": "0x000000000000000000000000000000000000dEaD", "data": _hex_zero_bytes(1600)}
        res = await middleware("eth_call", [tx, "latest"])
        # If compressed path is successful, expect 0x1234, else fallback to 0xabcd
        assert res == ({"result": "0x1234"} if not fail else {"result": "0xabcd"})
        # Verify override used in first call
        first = prov.calls[0]
        assert first["params"][0]["to"] == DECOMPRESSOR_ADDRESS
        assert isinstance(first["params"][2], dict)

    asyncio.run(run_case())


def test_async_middleware_merges_override():
    mw = AsyncCompressionMiddleware(alg="cd", min_size=0, allow_fallback=True)
    prov = FakeAsyncProvider()
    w3 = AW3(prov)

    async def make_request(method, params):
        return await prov.make_request(method, params)

    middleware = mw(make_request, w3)

    async def run_case():
        tx = {"to": "0x000000000000000000000000000000000000dEaD", "data": _hex_zero_bytes(1600)}
        existing = {"0x0000000000000000000000000000000000000002": {"code": "0x5f5ff3"}}
        _ = await middleware("eth_call", [tx, "latest", existing])
        merged = prov.calls[-1]["params"][2]
        assert (
            DECOMPRESSOR_ADDRESS.lower() in merged
            and "0x0000000000000000000000000000000000000002" in merged
        )

    asyncio.run(run_case())
