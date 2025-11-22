from __future__ import annotations

from typing import Any

from .compressor import DECOMPRESSOR_ADDRESS, compress_call_data


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
        def middleware(method: str, params: list) -> dict[str, Any]:
            if method != "eth_call":
                return dict(make_request(method, params))

            if not params:
                return dict(make_request(method, params))

            # Parse eth_call params: [tx, block/tag?, override?]
            tx = params[0] if len(params) >= 1 else {}
            block = params[1] if len(params) >= 2 else "latest"
            existing_override = params[2] if len(params) >= 3 else None

            to = tx.get("to")
            data_hex = tx.get("data")
            if not to or not data_hex:
                return dict(make_request(method, params))

            try:
                new_to, new_data, override, meta = compress_call_data(
                    data_hex, to, alg=self.alg, min_size=self.min_size
                )
            except Exception:
                return dict(make_request(method, params))

            if meta.get("algo") == "vanilla":
                return dict(make_request(method, params))

            # Merge overrides if possible (simple merge; if conflicts, skip compression)
            merged_override = None
            try:
                if existing_override and override:
                    # best effort: if both set code for decompressor address, prefer existing
                    merged = {**override}
                    for k, v in existing_override.items():
                        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                            merged[k] = {**merged[k], **v}
                        else:
                            merged[k] = v
                    merged_override = merged
                else:
                    merged_override = existing_override or override
            except Exception:
                merged_override = existing_override or override

            new_tx = {"to": new_to, "data": new_data}
            payload = [new_tx, block]
            if merged_override:
                payload.append(merged_override)

            res = make_request("eth_call", payload)
            if "result" in res:
                return dict(res)

            if self.allow_fallback:
                return dict(make_request(method, params))
            return dict(res)

        return middleware

    def __call__(self, *args):  # v6/v7 compatibility
        # v6 signature: (make_request, w3)
        if len(args) == 2:
            make_request, w3 = args
            return self._build(make_request, w3)
        # v7 signature: (w3) -> object with wrap_make_request(make_request)
        if len(args) == 1:
            w3 = args[0]

            parent = self

            class V7Adapter:
                def __init__(self, w3_):
                    self.w3 = w3_

                def wrap_make_request(self, make_request):
                    return parent._build(make_request, self.w3)

            return V7Adapter(w3)
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
        async def middleware(method: str, params: list) -> dict:
            if method != "eth_call" or not params:
                return dict(await make_request(method, params))

            tx = params[0] if len(params) >= 1 else {}
            block = params[1] if len(params) >= 2 else "latest"
            existing_override = params[2] if len(params) >= 3 else None

            to = tx.get("to")
            data_hex = tx.get("data")
            if not to or not data_hex:
                return dict(await make_request(method, params))

            try:
                new_to, new_data, override, meta = compress_call_data(
                    data_hex, to, alg=self.alg, min_size=self.min_size
                )
            except Exception:
                return dict(await make_request(method, params))

            if meta.get("algo") == "vanilla":
                return dict(await make_request(method, params))

            # Merge overrides if possible
            merged_override = None
            try:
                if existing_override and override:
                    merged = {**override}
                    for k, v in existing_override.items():
                        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                            merged[k] = {**merged[k], **v}
                        else:
                            merged[k] = v
                    merged_override = merged
                else:
                    merged_override = existing_override or override
            except Exception:
                merged_override = existing_override or override

            new_tx = {"to": new_to, "data": new_data}
            payload = [new_tx, block]
            if merged_override:
                payload.append(merged_override)

            res = await make_request("eth_call", payload)
            if isinstance(res, dict) and "result" in res:
                return dict(res)

            if self.allow_fallback:
                return dict(await make_request(method, params))
            return dict(res)

        return middleware

    def __call__(self, *args):  # v6/v7 compatibility
        if len(args) == 2:
            make_request, w3 = args
            return self._build(make_request, w3)
        if len(args) == 1:
            w3 = args[0]

            parent = self

            class V7AsyncAdapter:
                def __init__(self, w3_):
                    self.w3 = w3_

                def wrap_make_request(self, make_request):
                    return parent._build(make_request, self.w3)

            return V7AsyncAdapter(w3)
        raise TypeError("AsyncCompressionMiddleware: expected (make_request, w3) or (w3)")


__all__ = ["DECOMPRESSOR_ADDRESS", "AsyncCompressionMiddleware", "CompressionMiddleware"]
