from __future__ import annotations

import random

from eth.vm.message import Message
from eth.vm.transaction_context import BaseTransactionContext
import pytest

from ethcompress.compressor import compress_call_data
from ethcompress.jit import jit_bytecode

from .evm_helpers import (
    DECOMPRESSOR_ADDRESS,
    ECHO_CONTRACT_ADDRESS,
    create_test_evm,
    execute_call_with_state_override,
)


def execute(state, to, data, *, gas=1_000_000, value=0):
    sender = b"\xaa" * 20
    state.set_balance(sender, 10**18)
    state.set_balance(to, value)
    message = Message(
        to=to, sender=sender, value=value, data=data, code=state.get_code(to), gas=gas
    )
    context = BaseTransactionContext(origin=sender, gas_price=1)
    return state.computation_class.apply_computation(state, message, context)


@pytest.mark.parametrize("alg", ["jit", "flz", "cd"])
@pytest.mark.parametrize(
    ("target_code", "expected_error", "expected_output"),
    [
        ("5f5ff3", False, b""),
        ("63deadbeef5f526004601cf3", False, bytes.fromhex("deadbeef")),
        ("5f5ffd", True, b""),
        ("63deadbeef5f526004601cfd", True, bytes.fromhex("deadbeef")),
        ("365f5f37365ffd", True, b"\x00" * 1600),
        ("fe", True, b""),  # Exceptional halt, not a REVERT opcode.
        ("5b5f56", True, b""),  # The inner call exhausts its forwarded gas.
    ],
)
def test_forwarder_preserves_success_and_revert(alg, target_code, expected_error, expected_output):
    state = create_test_evm().get_vm().state
    state.set_code(ECHO_CONTRACT_ADDRESS, bytes.fromhex(target_code))
    data = b"\x00" * 1600
    to, compressed, overrides, meta = compress_call_data(
        data, "0x" + ECHO_CONTRACT_ADDRESS.hex(), alg=alg, min_size=0
    )
    assert meta["algo"] == alg
    for address, override in overrides.items():
        state.set_code(bytes.fromhex(address[2:]), bytes.fromhex(override["code"][2:]))
    vanilla = execute(state, ECHO_CONTRACT_ADDRESS, data)
    forwarded = execute(state, bytes.fromhex(to[2:]), bytes.fromhex(compressed[2:]))
    assert vanilla.is_error == forwarded.is_error == expected_error
    assert vanilla.output == forwarded.output == expected_output


@pytest.mark.parametrize("alg", ["jit", "flz", "cd"])
def test_forwarder_preserves_origin_and_value(alg):
    state = create_test_evm().get_vm().state
    state.set_code(ECHO_CONTRACT_ADDRESS, bytes.fromhex("325f523460205260405ff3"))
    data = b"\x00" * 1600
    to, compressed, overrides, _ = compress_call_data(
        data, "0x" + ECHO_CONTRACT_ADDRESS.hex(), alg=alg, min_size=0
    )
    for address, override in overrides.items():
        state.set_code(bytes.fromhex(address[2:]), bytes.fromhex(override["code"][2:]))
    vanilla = execute(state, ECHO_CONTRACT_ADDRESS, data, value=17)
    forwarded = execute(state, bytes.fromhex(to[2:]), bytes.fromhex(compressed[2:]), value=17)
    assert not vanilla.is_error and not forwarded.is_error
    assert forwarded.output == vanilla.output


def test_large_jit_program_has_valid_return_jump():
    data = random.Random(42).randbytes(70_000)
    code = bytes.fromhex(jit_bytecode("0x" + data.hex())[2:])
    assert len(code) > 65_535
    result, _ = execute_call_with_state_override(
        create_test_evm(),
        DECOMPRESSOR_ADDRESS,
        ECHO_CONTRACT_ADDRESS.rjust(32, b"\x00"),
        {DECOMPRESSOR_ADDRESS: code},
    )
    assert result == data
