from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from web3 import AsyncWeb3, Web3
from web3.providers.async_base import AsyncBaseProvider
from web3.providers.base import BaseProvider

from ethcompress.middleware import (
    DECOMPRESSOR_ADDRESS,
    AsyncCompressionMiddleware,
    CompressionMiddleware,
)

TARGET = "0x" + "11" * 20


class RecordingProvider(BaseProvider):
    def __init__(self, failure=None):
        super().__init__()
        self.calls = []
        self.failure = failure

    def make_request(self, method, params):
        self.calls.append((method, deepcopy(params)))
        if params and isinstance(params[0], dict) and params[0].get("to") == DECOMPRESSOR_ADDRESS:
            if self.failure == "transport":
                raise OSError("connection interrupted")
            if self.failure == "rpc":
                return {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": 3, "message": "execution reverted", "data": "0xdeadbeef"},
                }
        return {"jsonrpc": "2.0", "id": 1, "result": "0x1234"}


class AsyncRecordingProvider(AsyncBaseProvider):
    def __init__(self, recorder):
        super().__init__()
        self.recorder = recorder

    async def make_request(self, method, params):
        return self.recorder.make_request(method, params)


def client(is_async, *, failure=None, allow_fallback=False, keep_defaults=False):
    recorder = RecordingProvider(failure)
    if is_async:
        w3 = AsyncWeb3(AsyncRecordingProvider(recorder))
        middleware = AsyncCompressionMiddleware(alg="cd", allow_fallback=allow_fallback)
    else:
        w3 = Web3(recorder)
        middleware = CompressionMiddleware(alg="cd", allow_fallback=allow_fallback)
    if not keep_defaults:
        w3.middleware_onion.clear()
    w3.middleware_onion.add(middleware)
    return w3, recorder


def request(w3, method, params):
    if isinstance(w3, AsyncWeb3):
        return asyncio.run(w3.manager.coro_request(method, params))
    return w3.manager.request_blocking(method, params)


def call_params():
    return [
        {
            "to": TARGET,
            "data": "0x" + "00" * 1600,
            "from": "0x" + "22" * 20,
            "gas": "0x100000",
            "value": "0x11",
            "maxFeePerGas": "0x10",
            "maxPriorityFeePerGas": "0x1",
            "accessList": [],
        },
        {"blockHash": "0x" + "33" * 32, "requireCanonical": True},
        {
            TARGET: {
                "code": "0x5f5ff3",
                "balance": "0x17",
                "stateDiff": {"0x" + "00" * 32: "0x" + "01" * 32},
            }
        },
        {"time": "0x1234"},
    ]


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.parametrize("keep_defaults", [False, True])
def test_real_web3_eth_call(is_async, keep_defaults):
    w3, recorder = client(is_async, keep_defaults=keep_defaults)
    tx = {"to": TARGET, "data": "0x" + "00" * 1600}
    result = asyncio.run(w3.eth.call(tx, "latest")) if is_async else w3.eth.call(tx, "latest")
    assert result == bytes.fromhex("1234")
    calls = [params for method, params in recorder.calls if method == "eth_call"]
    assert len(calls) == 1
    assert calls[0][0]["to"] == DECOMPRESSOR_ADDRESS


@pytest.mark.parametrize("is_async", [False, True])
def test_preserves_call_fields_and_overrides_without_mutation(is_async):
    w3, recorder = client(is_async)
    params = call_params()
    original = deepcopy(params)
    assert request(w3, "eth_call", params) == "0x1234"
    assert params == original
    sent = recorder.calls[0][1]
    assert sent[0]["to"] == DECOMPRESSOR_ADDRESS
    for key, value in params[0].items():
        if key not in ("to", "data"):
            assert sent[0][key] == value
    assert sent[1] == params[1]
    assert sent[2][TARGET] == params[2][TARGET]
    assert "code" in sent[2][DECOMPRESSOR_ADDRESS.lower()]
    assert sent[3:] == params[3:]


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.parametrize("address", [DECOMPRESSOR_ADDRESS, DECOMPRESSOR_ADDRESS.lower()])
@pytest.mark.parametrize("override", [{"code": "0x00"}, {"balance": "0x10"}])
def test_decompressor_override_collision_skips_compression(is_async, address, override):
    w3, recorder = client(is_async)
    params = call_params()
    params[2][address] = override
    assert request(w3, "eth_call", params) == "0x1234"
    assert recorder.calls == [("eth_call", params)]


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.parametrize("failure", ["transport", "rpc"])
@pytest.mark.parametrize("allow_fallback", [False, True])
def test_fallback_uses_exact_original_request(is_async, failure, allow_fallback):
    w3, recorder = client(is_async, failure=failure, allow_fallback=allow_fallback)
    params = call_params()
    if allow_fallback:
        assert request(w3, "eth_call", params) == "0x1234"
        assert len(recorder.calls) == 2
        assert recorder.calls[-1] == ("eth_call", params)
    else:
        error = OSError if failure == "transport" else Exception
        message = "connection interrupted" if failure == "transport" else "execution reverted"
        with pytest.raises(error, match=message):
            request(w3, "eth_call", params)
        assert len(recorder.calls) == 1


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.parametrize("allow_fallback", [False, True])
def test_compression_failure_respects_fallback(monkeypatch, is_async, allow_fallback):
    def broken_compressor(*args, **kwargs):
        raise ValueError("cannot compress")

    monkeypatch.setattr("ethcompress.middleware.compress_call_data", broken_compressor)
    w3, recorder = client(is_async, allow_fallback=allow_fallback)
    params = call_params()
    if allow_fallback:
        assert request(w3, "eth_call", params) == "0x1234"
        assert recorder.calls == [("eth_call", params)]
    else:
        with pytest.raises(ValueError, match="cannot compress"):
            request(w3, "eth_call", params)
        assert not recorder.calls


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("eth_call", []),
        ("eth_call", [{"to": TARGET}]),
        ("eth_call", [{"to": TARGET, "data": "0x1234"}, "latest"]),
        ("eth_getCode", [TARGET, "latest"]),
    ],
)
def test_passthrough_is_not_fallback(is_async, method, params):
    w3, recorder = client(is_async, allow_fallback=False)
    assert request(w3, method, params) == "0x1234"
    assert recorder.calls == [(method, params)]
