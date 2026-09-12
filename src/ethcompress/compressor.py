from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compressions.utils import to_hex as _to_hex

from .jit import flz_fwd_bytecode, jit_bytecode, rle_fwd_bytecode
from .libzip import cd_compress, flz_compress

HexLike = str | bytes


# Checksum form is required by Web3 v6's default address-validation middleware.
DECOMPRESSOR_ADDRESS = "0x00000000000000000000000000000000000000E0"


def _norm_hex(s: str) -> str:
    s = s.strip().lower()
    return s[2:] if s.startswith("0x") else s


def _pad32(hex_no_prefix: str) -> str:
    return hex_no_prefix.rjust(64, "0")


def _address_word(addr: str) -> str:
    a = _norm_hex(addr)
    if len(a) != 40:
        a = a[-40:].rjust(40, "0")
    return "0x" + _pad32(a)


def _size_bytes(hex_with_prefix: str) -> int:
    h = hex_with_prefix[2:] if hex_with_prefix.startswith("0x") else hex_with_prefix
    return len(h) // 2


@dataclass
class CompressedCall:
    to: str
    data: str
    override: dict[str, dict[str, str]] | None
    algo: str
    sizes: dict[str, int]
    supported: bool = True
    benefit: dict[str, float] | None = None
    allow_fallback: bool = True
    _vanilla: tuple[str, str] | None = None

    def execute(self, w3: Any, block: str | int = "latest") -> str:
        tx = {"to": self.to, "data": self.data}
        override_payload = self.override if self.override else None

        # Skipping compression is a normal call, not a failed compressed attempt.
        if override_payload is None:
            res = w3.provider.make_request("eth_call", [tx, block])
            if isinstance(res, dict) and "result" in res:
                return str(res["result"])
            raise RuntimeError(f"eth_call failed: {res}")

        try:
            res = w3.provider.make_request("eth_call", [tx, block, override_payload])
        except Exception:
            if not self.allow_fallback:
                raise
        else:
            if isinstance(res, dict) and "result" in res:
                return str(res["result"])
            if not self.allow_fallback:
                raise RuntimeError(f"compressed eth_call failed: {res}")

        if not self.allow_fallback or not self._vanilla:
            raise RuntimeError("compressed call failed and fallback disabled")

        to0, data0 = self._vanilla
        res = w3.provider.make_request("eth_call", [{"to": to0, "data": data0}, block])
        if "result" in res:
            return str(res["result"])
        raise RuntimeError(f"fallback eth_call failed: {res}")


def compress_call_data(
    data: HexLike,
    target: str,
    *,
    alg: str = "auto",
    min_size: int = 800,
) -> tuple[str, str, dict[str, dict[str, str]] | None, dict[str, Any]]:
    data_hex = _to_hex(data)
    original_size = _size_bytes(data_hex)
    if original_size < min_size:
        meta = {
            "algo": "vanilla",
            "sizes": {"original": original_size, "compressed": original_size, "code": 0},
            "benefit": {"bytes_saved": 0, "pct": 0.0},
        }
        return target, data_hex, None, meta

    if alg not in ("auto", "jit", "flz", "cd"):
        raise ValueError(f"unknown compression algorithm: {alg}")

    # Compare complete codec payloads, including each candidate's forwarder bytecode.
    # Large calldata is not necessarily best served by JIT (e.g. repeated addresses).
    candidates: list[tuple[int, str, str, str]] = []
    for candidate in ("jit", "flz", "cd") if alg == "auto" else (alg,):
        try:
            if candidate == "jit":
                code = jit_bytecode(data_hex)
                calldata = _address_word(target)
            elif candidate == "flz":
                code = flz_fwd_bytecode(target)
                calldata = flz_compress(data_hex)
            else:
                code = rle_fwd_bytecode(target)
                calldata = cd_compress(data_hex)
        except Exception:
            if alg != "auto":
                raise
            continue
        candidates.append((_size_bytes(code) + _size_bytes(calldata), candidate, calldata, code))

    if not candidates or min(candidates)[0] >= original_size:
        meta = {
            "algo": "vanilla",
            "sizes": {"original": original_size, "compressed": original_size, "code": 0},
            "benefit": {"bytes_saved": 0, "pct": 0.0},
        }
        return target, data_hex, None, meta

    total_sel, selected, calldata_sel, code_sel = min(candidates)

    override = {DECOMPRESSOR_ADDRESS.lower(): {"code": code_sel}}
    benefit_bytes = original_size - total_sel
    benefit_pct = (benefit_bytes / original_size) * 100 if original_size else 0.0
    meta = {
        "algo": selected,
        "sizes": {
            "original": original_size,
            "compressed": _size_bytes(calldata_sel),
            "code": _size_bytes(code_sel),
        },
        "benefit": {"bytes_saved": benefit_bytes, "pct": benefit_pct},
    }
    return DECOMPRESSOR_ADDRESS, calldata_sel, override, meta


def compress_eth_call(
    to: str,
    data: HexLike,
    *,
    alg: str = "auto",
    min_size: int = 800,
    allow_fallback: bool = True,
) -> CompressedCall:
    new_to, new_data, override, meta = compress_call_data(data, to, alg=alg, min_size=min_size)
    algo = meta["algo"]
    if algo == "vanilla":
        sizes = meta["sizes"]
        return CompressedCall(
            to=to,
            data=_to_hex(data),
            override=None,
            algo=algo,
            sizes=sizes,
            supported=True,
            benefit=meta.get("benefit"),
            allow_fallback=allow_fallback,
            _vanilla=(to, _to_hex(data)),
        )

    tx_to = new_to
    tx_data = new_data
    sizes = meta["sizes"]
    cc = CompressedCall(
        to=tx_to,
        data=tx_data,
        override=override,
        algo=algo,
        sizes=sizes,
        supported=True,
        benefit=meta.get("benefit"),
        allow_fallback=allow_fallback,
        _vanilla=(to, _to_hex(data)),
    )
    return cc


def compress_call_fn(
    fn: Any,
    *,
    alg: str = "auto",
    min_size: int = 800,
    allow_fallback: bool = True,
) -> CompressedCall:
    try:
        to = fn.address  # ContractFunction
    except Exception as e:
        raise TypeError("fn must be a web3 ContractFunction with .address") from e
    try:
        data_hex = fn._encode_transaction_data()
    except Exception:
        data_hex = fn._encode_transaction_data  # py-evm style attribute sometimes
        if callable(data_hex):
            data_hex = data_hex()
    return compress_eth_call(
        to, data_hex, alg=alg, min_size=min_size, allow_fallback=allow_fallback
    )


__all__ = [
    "DECOMPRESSOR_ADDRESS",
    "CompressedCall",
    "compress_call_data",
    "compress_call_fn",
    "compress_eth_call",
]
