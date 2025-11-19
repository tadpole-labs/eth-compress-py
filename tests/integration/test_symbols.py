import os
import threading
import time

import pytest

from ethcompress import cd_compress, flz_compress, flz_fwd_bytecode, jit_bytecode, rle_fwd_bytecode
from tests.integration.addresses_data import ADDRESSES
from tests.integration.helpers import (
    DECOMPRESSOR_ADDRESS,
    MULTICALL3,
    build_aggregate_calldata,
    decode_aggregate_output,
    provider_supports_state_override,
    try_eth_call_with_state_override,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("WEB3_PROVIDER_URL"), reason="Set WEB3_PROVIDER_URL to run integration tests"
)


def test_symbols_end_to_end():
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(os.environ["WEB3_PROVIDER_URL"], request_kwargs={"timeout": 90}))

    targets = ADDRESSES
    data_hex, _calls = build_aggregate_calldata(w3, targets)
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
    try:
        v = raw_v.hex()
    except Exception:
        v = str(raw_v)
    vanilla_hex = v if v.startswith("0x") else ("0x" + v)
    print(f"symbols RAW: time_ms={(t1_v-t0_v)*1000:.2f}, calldata_bytes={(len(data_hex)-2)//2}")
    _bn_v, ret_v = decode_aggregate_output(w3, vanilla_hex)

    t0_cd, t1_cd, raw_cd = results["cd"]
    _bn_cd, ret_cd = decode_aggregate_output(w3, raw_cd)
    assert ret_cd == ret_v
    print(
        f"symbols CD: time_ms={(t1_cd-t0_cd)*1000:.2f}, compressed_bytes={(len(cd_data)-2)//2}, code_bytes={(len(cd_code)-2)//2}"
    )

    t0_flz, t1_flz, raw_flz = results["flz"]
    _bn_flz, ret_flz = decode_aggregate_output(w3, raw_flz)
    assert ret_flz == ret_v
    print(
        f"symbols FLZ: time_ms={(t1_flz-t0_flz)*1000:.2f}, compressed_bytes={(len(flz_data)-2)//2}, code_bytes={(len(flz_code)-2)//2}"
    )

    t0_jit, t1_jit, raw_jit = results["jit"]
    _bn_jit, ret_jit = decode_aggregate_output(w3, raw_jit)
    assert ret_jit == ret_v
    print(
        f"symbols JIT: time_ms={(t1_jit-t0_jit)*1000:.2f}, calldata_bytes={(len(jit_calldata)-2)//2}, code_bytes={(len(jit_code)-2)//2}"
    )
