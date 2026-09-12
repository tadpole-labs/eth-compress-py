from __future__ import annotations

from .compressor import DECOMPRESSOR_ADDRESS, compress_call_data


def _compressed_params(params: list, *, alg: str, min_size: int) -> list | None:
    if not params:
        return None
    tx = params[0]
    to = tx.get("to")
    data = tx.get("data")
    if not to or not data:
        return None
    existing_override = params[2] if len(params) >= 3 else None
    # Any override at this address belongs to the caller, regardless of checksum case.
    if existing_override and any(
        address.lower() == DECOMPRESSOR_ADDRESS.lower() for address in existing_override
    ):
        return None
    new_to, new_data, override, meta = compress_call_data(data, to, alg=alg, min_size=min_size)
    if meta["algo"] == "vanilla":
        return None

    payload = list(params)
    payload[0] = {**tx, "to": new_to, "data": new_data}
    if len(payload) < 2:
        payload.append("latest")
    merged_override = {**(existing_override or {}), **(override or {})}
    if len(payload) < 3:
        payload.append(merged_override)
    else:
        payload[2] = merged_override
    return payload


class CompressionMiddleware:
    def __init__(
        self,
        *,
        alg: str = "auto",
        min_size: int = 800,
        allow_fallback: bool = True,
    ) -> None:
        self.alg = alg
        self.min_size = min_size
        self.allow_fallback = allow_fallback

    def _build(self, make_request, w3):
        def middleware(method, params):
            if method != "eth_call":
                return make_request(method, params)
            try:
                payload = _compressed_params(params, alg=self.alg, min_size=self.min_size)
            except Exception:
                if not self.allow_fallback:
                    raise
                return make_request(method, params)
            if payload is None:
                return make_request(method, params)
            try:
                result = make_request(method, payload)
            except Exception:
                if not self.allow_fallback:
                    raise
            else:
                if "result" in result or not self.allow_fallback:
                    return result
            return make_request(method, params)

        return middleware

    def __call__(self, *args):  # v6/v7 compatibility
        if len(args) == 2:
            return self._build(*args)
        if len(args) == 1:
            parent = self

            class V7Adapter:
                def wrap_make_request(self, make_request):
                    return parent._build(make_request, args[0])

            return V7Adapter()
        raise TypeError("CompressionMiddleware: expected (make_request, w3) or (w3)")


class AsyncCompressionMiddleware:
    def __init__(
        self,
        *,
        alg: str = "auto",
        min_size: int = 800,
        allow_fallback: bool = True,
    ) -> None:
        self.alg = alg
        self.min_size = min_size
        self.allow_fallback = allow_fallback

    def _build(self, make_request, w3):
        async def middleware(method, params):
            if method != "eth_call":
                return await make_request(method, params)
            try:
                payload = _compressed_params(params, alg=self.alg, min_size=self.min_size)
            except Exception:
                if not self.allow_fallback:
                    raise
                return await make_request(method, params)
            if payload is None:
                return await make_request(method, params)
            try:
                result = await make_request(method, payload)
            except Exception:
                if not self.allow_fallback:
                    raise
            else:
                if "result" in result or not self.allow_fallback:
                    return result
            return await make_request(method, params)

        return middleware

    def __call__(self, *args):  # v6/v7 compatibility
        if len(args) == 2:

            async def build():
                return self._build(*args)

            return build()
        if len(args) == 1:
            parent = self

            class V7AsyncAdapter:
                async def async_wrap_make_request(self, make_request):
                    return parent._build(make_request, args[0])

            return V7AsyncAdapter()
        raise TypeError("AsyncCompressionMiddleware: expected (make_request, w3) or (w3)")


__all__ = ["DECOMPRESSOR_ADDRESS", "AsyncCompressionMiddleware", "CompressionMiddleware"]
