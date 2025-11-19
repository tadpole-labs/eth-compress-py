import os
import threading
import time

import pytest
from web3 import Web3

from ethcompress import cd_compress, flz_compress, flz_fwd_bytecode, jit_bytecode, rle_fwd_bytecode
from tests.integration.addresses_data import ADDRESSES
from tests.integration.helpers import (
    DECOMPRESSOR_ADDRESS,
    MULTICALL3,
    decode_aggregate_output,
    provider_supports_state_override,
    try_eth_call_with_state_override,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("WEB3_PROVIDER_URL"), reason="Set WEB3_PROVIDER_URL to run integration tests"
)


def _build_calldata_for_calls(w3: Web3, calls: list) -> str:
    mc = w3.eth.contract(
        address=Web3.to_checksum_address(MULTICALL3),
        abi=[
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
        ],
    )
    if hasattr(mc, "encode_abi"):
        return str(mc.encode_abi("aggregate", args=[calls]))
    return str(mc.encodeABI(fn_name="aggregate", args=[calls]))


def _selector(text: str) -> bytes:
    return bytes(Web3.keccak(text=text)[:4])


def _encode_address_param(addr: str) -> bytes:
    a = Web3.to_checksum_address(addr)
    n = int(a, 16)
    return n.to_bytes(32, byteorder="big")


def test_integration_balances_timings():
    w3 = Web3(Web3.HTTPProvider(os.environ["WEB3_PROVIDER_URL"], request_kwargs={"timeout": 90}))
    owner = os.getenv("BALANCE_OWNER", "0x0000000000000000000000000000000000000000")
    sel_bal = _selector("balanceOf(address)")
    arg = _encode_address_param(owner)
    calls = [(t, sel_bal + arg) for t in ADDRESSES]

    data_hex = _build_calldata_for_calls(w3, calls)
    tx = {"to": MULTICALL3, "data": data_hex, "gas": 30_000_000}

    # warmup request
    _ = w3.eth.block_number
    time.sleep(0.2)

    if not provider_supports_state_override(w3):
        pytest.skip("Provider does not support eth_call state override")

    # Prepare all compression data upfront
    cd_data = cd_compress(data_hex)
    cd_code = rle_fwd_bytecode(MULTICALL3)
    tx_cd = {"to": DECOMPRESSOR_ADDRESS, "data": cd_data, "gas": 30_000_000}

    flz_data = flz_compress(data_hex)
    flz_code = flz_fwd_bytecode(MULTICALL3)
    tx_flz = {"to": DECOMPRESSOR_ADDRESS, "data": flz_data, "gas": 30_000_000}

    jit_code = jit_bytecode(data_hex)
    addr_hex = MULTICALL3[2:]
    jit_calldata = "0x" + addr_hex.rjust(64, "0")
    tx_jit = {"to": DECOMPRESSOR_ADDRESS, "data": jit_calldata, "gas": 30_000_000}

    # Results storage
    results = {}

    def benchmark_vanilla(delay: float) -> None:
        time.sleep(delay)
        t0 = time.perf_counter()
        raw = w3.eth.call(tx)
        t1 = time.perf_counter()
        results["vanilla"] = (t0, t1, raw)

    def benchmark_cd(delay: float) -> None:
        time.sleep(delay)
        t0 = time.perf_counter()
        raw = try_eth_call_with_state_override(w3, tx_cd, cd_code)
        t1 = time.perf_counter()
        results["cd"] = (t0, t1, raw)

    def benchmark_flz(delay: float) -> None:
        time.sleep(delay)
        t0 = time.perf_counter()
        raw = try_eth_call_with_state_override(w3, tx_flz, flz_code)
        t1 = time.perf_counter()
        results["flz"] = (t0, t1, raw)

    def benchmark_jit(delay: float) -> None:
        time.sleep(delay)
        t0 = time.perf_counter()
        raw = try_eth_call_with_state_override(w3, tx_jit, jit_code)
        t1 = time.perf_counter()
        results["jit"] = (t0, t1, raw)

    # Submit requests at fixed 200ms intervals
    threads = [
        threading.Thread(target=benchmark_vanilla, args=(0.0,)),
        threading.Thread(target=benchmark_cd, args=(0.2,)),
        threading.Thread(target=benchmark_flz, args=(0.4,)),
        threading.Thread(target=benchmark_jit, args=(0.6,)),
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    # Process results
    t0_v, t1_v, raw_v = results["vanilla"]
    v = raw_v.hex() if hasattr(raw_v, "hex") else str(raw_v)
    vanilla_hex = v if v.startswith("0x") else ("0x" + v)
    print(f"balances RAW: time_ms={(t1_v-t0_v)*1000:.2f}, calldata_bytes={(len(data_hex)-2)//2}")
    _bn_v, ret_v = decode_aggregate_output(w3, vanilla_hex)

    t0_cd, t1_cd, raw_cd = results["cd"]
    _bn_cd, ret_cd = decode_aggregate_output(w3, raw_cd)
    assert ret_cd == ret_v
    print(
        f"balances CD: time_ms={(t1_cd-t0_cd)*1000:.2f}, compressed={(len(cd_data)-2)//2}, code={(len(cd_code)-2)//2}"
    )

    t0_flz, t1_flz, raw_flz = results["flz"]
    _bn_flz, ret_flz = decode_aggregate_output(w3, raw_flz)
    assert ret_flz == ret_v
    print(
        f"balances FLZ: time_ms={(t1_flz-t0_flz)*1000:.2f}, compressed={(len(flz_data)-2)//2}, code={(len(flz_code)-2)//2}"
    )

    t0_jit, t1_jit, raw_jit = results["jit"]
    _bn_jit, ret_jit = decode_aggregate_output(w3, raw_jit)
    assert ret_jit == ret_v
    print(
        f"balances JIT: time_ms={(t1_jit-t0_jit)*1000:.2f}, calldata={(len(jit_calldata)-2)//2}, code={(len(jit_code)-2)//2}"
    )
