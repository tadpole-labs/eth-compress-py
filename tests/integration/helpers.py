from __future__ import annotations

from requests.exceptions import HTTPError
from web3 import Web3

from ethcompress.compressor import DECOMPRESSOR_ADDRESS as _DECOMP

MULTICALL3 = Web3.to_checksum_address("0xcA11bde05977b3631167028862bE2a173976CA11")
DECOMPRESSOR_ADDRESS = Web3.to_checksum_address(_DECOMP)

MULTICALL3_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "target", "type": "address"},
                    {"internalType": "bytes", "name": "callData", "type": "bytes"},
                ],
                "internalType": "struct Multicall3.Call[]",
                "name": "calls",
                "type": "tuple[]",
            }
        ],
        "name": "aggregate",
        "outputs": [
            {"internalType": "uint256", "name": "blockNumber", "type": "uint256"},
            {"internalType": "bytes[]", "name": "returnData", "type": "bytes[]"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


def build_aggregate_calldata(w3: Web3, targets: list[str]) -> tuple[str, list[tuple[str, bytes]]]:
    selector = Web3.keccak(text="symbol()")[:4]
    calls = [(t, selector) for t in targets]
    mc = w3.eth.contract(address=MULTICALL3, abi=MULTICALL3_ABI)
    calls_arg = list(calls)
    if hasattr(mc, "encode_abi"):
        data = mc.encode_abi("aggregate", args=[calls_arg])
    else:
        data = mc.encodeABI(fn_name="aggregate", args=[calls_arg])
    return data, calls


def try_eth_call_with_state_override(w3: Web3, tx: dict, bytecode: str) -> str:
    overrides_map = {DECOMPRESSOR_ADDRESS: {"code": bytecode}}
    shapes = [
        overrides_map,
        {"stateOverride": overrides_map},
        {"stateOverrides": overrides_map},
    ]
    tx_variants = [tx]
    if "gas" in tx:
        tx_wo = dict(tx)
        tx_wo.pop("gas", None)
        tx_variants.append(tx_wo)
    last_err: Exception | None = None
    for shape in shapes:
        for txv in tx_variants:
            payload = [txv, "latest", shape]
            try:
                resp = w3.provider.make_request("eth_call", payload)
                if isinstance(resp, dict) and "result" in resp:
                    return str(resp["result"])
                last_err = RuntimeError(f"Unexpected response: {resp}")
            except HTTPError as he:
                try:
                    body = he.response.text
                except Exception:  # pragma: no cover - best effort logging
                    body = str(he)
                last_err = RuntimeError(f"HTTPError: {body}")
            except Exception as e:  # pragma: no cover - provider-specific
                last_err = e
                continue
    if last_err:
        raise last_err
    raise RuntimeError("eth_call with state override failed (no response)")


def provider_supports_state_override(w3: Web3) -> bool:
    test_code = "0x5f5ff3"
    test_tx = {"to": DECOMPRESSOR_ADDRESS, "data": "0x", "gas": 300000}
    overrides_map = {DECOMPRESSOR_ADDRESS: {"code": test_code}}
    payloads = [
        [test_tx, "latest", overrides_map],
        [test_tx, "latest", {"stateOverride": overrides_map}],
        [test_tx, "latest", {"stateOverrides": overrides_map}],
    ]
    for p in payloads:
        for txv in (test_tx, {k: v for k, v in test_tx.items() if k != "gas"}):
            p2 = [txv, p[1], p[2]]
            try:
                resp = w3.provider.make_request("eth_call", p2)
                if isinstance(resp, dict) and "result" in resp:
                    return True
            except Exception:
                continue
    return False


def decode_aggregate_output(w3: Web3, raw_hex: str) -> tuple[int, list[bytes]]:
    payload = bytes.fromhex(raw_hex[2:] if raw_hex.startswith("0x") else raw_hex)
    try:
        block_number, return_data = w3.codec.decode(["uint256", "bytes[]"], payload)
    except Exception:  # pragma: no cover - fallback for variant codecs
        from eth_abi import decode as abi_decode

        block_number, return_data = abi_decode(["uint256", "bytes[]"], payload)
    return int(block_number), list(return_data)
