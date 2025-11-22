"""
Roundtrip compression tests using py-evm against real data.

Tests JIT, FLZ, and CD compression algorithms by:
1. Loading real transactions from base-blocks.json
2. Compressing the calldata with each algorithm
3. Executing the compressed call in EVM with state override
4. Verifying the result matches the original calldata
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ethcompress import cd_compress, flz_compress, jit_bytecode
from ethcompress.compressor import DECOMPRESSOR_ADDRESS

from .evm_helpers import (
    DECOMPRESSOR_ADDRESS as DECOMPRESSOR_ADDRESS_BYTES,
    ECHO_CONTRACT_ADDRESS,
    bytes_to_hex,
    create_test_evm,
    execute_call_with_state_override,
    hex_to_bytes,
)


@dataclass
class Transaction:
    """Transaction data."""

    from_addr: str
    to: str
    input: str


@dataclass
class CompressionMetrics:
    """Metrics for a single transaction compression."""

    tx_index: int
    src_bytes: int
    jit_bytes: int | None = None
    jit_code_bytes: int | None = None
    jit_ratio: float | None = None
    jit_gas_used: int | None = None
    jit_roundtrip_success: bool = False
    flz_bytes: int | None = None
    flz_code_bytes: int | None = None
    flz_ratio: float | None = None
    flz_gas_used: int | None = None
    flz_roundtrip_success: bool = False
    cd_bytes: int | None = None
    cd_code_bytes: int | None = None
    cd_ratio: float | None = None
    cd_gas_used: int | None = None
    cd_roundtrip_success: bool = False
    failures: list[dict[str, Any]] | None = None


def _test_transaction_roundtrip(
    tx: Transaction, tx_index: int, chain
) -> CompressionMetrics:
    """Test a single transaction with all compression algorithms."""
    original_calldata = tx.input
    src_bytes = (len(original_calldata) - 2) // 2  # Remove 0x prefix

    metrics = CompressionMetrics(tx_index=tx_index, src_bytes=src_bytes)
    failures = []

    # Test JIT compression
    try:
        jit_code = jit_bytecode(original_calldata)
        jit_code_bytes = (len(jit_code) - 2) // 2

        # JIT calldata is the target address (32 bytes padded)
        # Use echo contract as target to get the decompressed data back
        echo_addr_hex = ECHO_CONTRACT_ADDRESS.hex()
        target_padded = "0x" + echo_addr_hex.rjust(64, "0")
        jit_calldata = target_padded
        jit_bytes = (len(jit_calldata) - 2) // 2

        metrics.jit_bytes = jit_bytes
        metrics.jit_code_bytes = jit_code_bytes
        total_jit = jit_bytes + jit_code_bytes
        metrics.jit_ratio = total_jit / src_bytes if src_bytes > 0 else 0

        # Execute with state override
        result, gas_used = execute_call_with_state_override(
            chain,
            to=DECOMPRESSOR_ADDRESS_BYTES,
            data=hex_to_bytes(jit_calldata),
            code_override={DECOMPRESSOR_ADDRESS_BYTES: hex_to_bytes(jit_code)},
        )

        metrics.jit_gas_used = gas_used
        reconstructed = bytes_to_hex(result)

        # Verify roundtrip
        if reconstructed.lower() == original_calldata.lower():
            metrics.jit_roundtrip_success = True
        else:
            failures.append(
                {
                    "algorithm": "jit",
                    "error": "Roundtrip mismatch",
                    "expected": original_calldata,
                    "reconstructed": reconstructed,
                    "payload": jit_calldata,
                }
            )
    except Exception as e:
        failures.append(
            {
                "algorithm": "jit",
                "error": str(e),
                "expected": original_calldata,
                "reconstructed": None,
                "payload": None,
            }
        )

    # Test FLZ compression
    try:
        flz_calldata = flz_compress(original_calldata)
        flz_bytes = (len(flz_calldata) - 2) // 2

        # Generate forwarder bytecode - use echo contract as target
        from compressions.fastlz import flz_fwd_bytecode

        echo_addr_hex = "0x" + ECHO_CONTRACT_ADDRESS.hex()
        flz_code = flz_fwd_bytecode(echo_addr_hex)
        flz_code_bytes = (len(flz_code) - 2) // 2

        metrics.flz_bytes = flz_bytes
        metrics.flz_code_bytes = flz_code_bytes
        total_flz = flz_bytes + flz_code_bytes
        metrics.flz_ratio = total_flz / src_bytes if src_bytes > 0 else 0

        # Execute with state override
        result, gas_used = execute_call_with_state_override(
            chain,
            to=DECOMPRESSOR_ADDRESS_BYTES,
            data=hex_to_bytes(flz_calldata),
            code_override={DECOMPRESSOR_ADDRESS_BYTES: hex_to_bytes(flz_code)},
        )

        metrics.flz_gas_used = gas_used
        reconstructed = bytes_to_hex(result)

        # Verify roundtrip
        if reconstructed.lower() == original_calldata.lower():
            metrics.flz_roundtrip_success = True
        else:
            failures.append(
                {
                    "algorithm": "flz",
                    "error": "Roundtrip mismatch",
                    "expected": original_calldata,
                    "reconstructed": reconstructed,
                    "payload": flz_calldata,
                }
            )
    except Exception as e:
        failures.append(
            {
                "algorithm": "flz",
                "error": str(e),
                "expected": original_calldata,
                "reconstructed": None,
                "payload": None,
            }
        )

    # Test CD (calldata) compression
    try:
        cd_calldata = cd_compress(original_calldata)
        cd_bytes = (len(cd_calldata) - 2) // 2

        # Generate RLE forwarder bytecode - use echo contract as target
        from compressions.calldata import rle_fwd_bytecode

        echo_addr_hex = "0x" + ECHO_CONTRACT_ADDRESS.hex()
        cd_code = rle_fwd_bytecode(echo_addr_hex)
        cd_code_bytes = (len(cd_code) - 2) // 2

        metrics.cd_bytes = cd_bytes
        metrics.cd_code_bytes = cd_code_bytes
        total_cd = cd_bytes + cd_code_bytes
        metrics.cd_ratio = total_cd / src_bytes if src_bytes > 0 else 0

        # Execute with state override
        result, gas_used = execute_call_with_state_override(
            chain,
            to=DECOMPRESSOR_ADDRESS_BYTES,
            data=hex_to_bytes(cd_calldata),
            code_override={DECOMPRESSOR_ADDRESS_BYTES: hex_to_bytes(cd_code)},
        )

        metrics.cd_gas_used = gas_used
        reconstructed = bytes_to_hex(result)

        # Verify roundtrip
        if reconstructed.lower() == original_calldata.lower():
            metrics.cd_roundtrip_success = True
        else:
            failures.append(
                {
                    "algorithm": "cd",
                    "error": "Roundtrip mismatch",
                    "expected": original_calldata,
                    "reconstructed": reconstructed,
                    "payload": cd_calldata,
                }
            )
    except Exception as e:
        failures.append(
            {
                "algorithm": "cd",
                "error": str(e),
                "expected": original_calldata,
                "reconstructed": None,
                "payload": None,
            }
        )

    if failures:
        metrics.failures = failures

    return metrics


def mean(values: list[float | int]) -> float:
    """Calculate mean of a list of values."""
    return sum(values) / len(values) if values else 0.0


def test_roundtrip_on_base_blocks():
    """Test compression roundtrips on real Base blockchain transactions."""
    # Load the fixture
    fixture_path = Path(__file__).parent / "fixture" / "base-blocks.json"
    with open(fixture_path, "r") as f:
        cached = json.load(f)

    blocks = cached["blocks"]
    MIN_CALLDATA_SIZE = 800

    # Collect transactions with significant calldata
    all_transactions: list[Transaction] = []
    for block in blocks:
        if "transactions" in block and isinstance(block["transactions"], list):
            for tx in block["transactions"]:
                if (
                    tx.get("to")
                    and tx.get("input")
                    and tx["input"] != "0x"
                    and len(tx["input"]) >= MIN_CALLDATA_SIZE
                ):
                    all_transactions.append(
                        Transaction(
                            from_addr=tx["from"], to=tx["to"], input=tx["input"]
                        )
                    )

    # If no transactions found, skip the test
    if len(all_transactions) == 0:
        pytest.skip("No transactions with sufficient calldata size found")

    # Limit to first 10 transactions for performance
    all_transactions = all_transactions[:200]
    
    print(f"\nTesting {len(all_transactions)} transactions from Base blocks...")

    results: list[CompressionMetrics] = []
    success_cnt = {"jit": 0, "flz": 0, "cd": 0}
    all_failures: list[dict[str, Any]] = []

    start_time = time.time()

    # Create EVM instance once
    chain = create_test_evm()

    # Test each transaction
    for i, tx in enumerate(all_transactions):
        metrics = _test_transaction_roundtrip(tx, i, chain)
        results.append(metrics)

        if metrics.jit_roundtrip_success:
            success_cnt["jit"] += 1
        if metrics.flz_roundtrip_success:
            success_cnt["flz"] += 1
        if metrics.cd_roundtrip_success:
            success_cnt["cd"] += 1

        if metrics.failures:
            all_failures.extend([{**f, "txIndex": i} for f in metrics.failures])

    elapsed_time = time.time() - start_time

    # Write failures to file if any
    if all_failures:
        failures_file = Path(__file__).parent / "fixture" / "base-blocks-failures.json"
        failure_report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "totalTested": len(results),
            "totalFailures": len(all_failures),
            "failures": [
                {
                    "txIndex": f["txIndex"],
                    "algorithm": f["algorithm"],
                    "error": f["error"],
                    "expectedLength": len(f["expected"]) if f.get("expected") else 0,
                    "reconstructedLength": len(f["reconstructed"])
                    if f.get("reconstructed")
                    else 0,
                    "expected": f.get("expected"),
                    "reconstructed": f.get("reconstructed"),
                    "compressedPayload": f.get("payload"),
                }
                for f in all_failures
            ],
        }
        with open(failures_file, "w") as f:
            json.dump(failure_report, f, indent=2)
        print(f"\n⚠️  Failures written to: {failures_file}")

    # Calculate statistics
    jit_ratios = [r.jit_ratio for r in results if r.jit_ratio is not None]
    flz_ratios = [r.flz_ratio for r in results if r.flz_ratio is not None]
    cd_ratios = [r.cd_ratio for r in results if r.cd_ratio is not None]

    jit_gas = [r.jit_gas_used for r in results if r.jit_gas_used is not None]
    flz_gas = [r.flz_gas_used for r in results if r.flz_gas_used is not None]
    cd_gas = [r.cd_gas_used for r in results if r.cd_gas_used is not None]

    src_sizes = [r.src_bytes for r in results]
    avg_src_size = mean(src_sizes)

    # Print results
    print(f"\n{'='*60}")
    print(f"ROUNDTRIP TEST RESULTS")
    print(f"{'='*60}")
    print(
        f"{len(results)} txs | JIT: \033[32m{success_cnt['jit']}\033[0m | "
        f"FLZ: \033[32m{success_cnt['flz']}\033[0m | "
        f"CD: \033[32m{success_cnt['cd']}\033[0m"
    )
    print(f"Avg Src Size: {avg_src_size:.1f} bytes")
    print(
        f"Compression Ratio: JIT {mean(jit_ratios)*100:.1f}% | "
        f"FLZ {mean(flz_ratios)*100:.1f}% | "
        f"CD {mean(cd_ratios)*100:.1f}%"
    )
    print(
        f"Gas Used: JIT {mean(jit_gas):.0f} | "
        f"FLZ {mean(flz_gas):.0f} | "
        f"CD {mean(cd_gas):.0f}"
    )
    print(f"Elapsed Time: {elapsed_time:.2f}s")
    print(f"{'='*60}\n")

    # Assertions
    assert success_cnt["jit"] == len(
        results
    ), f"JIT roundtrip failures: {len(results) - success_cnt['jit']}"
    assert success_cnt["flz"] == len(
        results
    ), f"FLZ roundtrip failures: {len(results) - success_cnt['flz']}"
    assert success_cnt["cd"] == len(
        results
    ), f"CD roundtrip failures: {len(results) - success_cnt['cd']}"
    assert len(results) > 0, "No transactions were tested"

