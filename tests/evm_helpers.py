"""EVM helpers for testing compression roundtrips with py-evm."""

from __future__ import annotations

from eth import constants
from eth.chains.base import MiningChain
from eth.db.atomic import AtomicDB
from eth.vm.forks.prague import PragueVM


# Echo Contract bytecode
# Returns whatever calldata it receives
# - CALLDATASIZE (0x36): Get size of calldata
# - PUSH0 (0x5f): Source offset = 0
# - PUSH0 (0x5f): Dest offset = 0
# - CALLDATACOPY (0x37): Copy calldata to memory
# - CALLDATASIZE (0x36): Get size again for return
# - PUSH0 (0x5f): Return offset = 0
# - RETURN (0xf3): Return memory
ECHO_CONTRACT_BYTECODE = bytes.fromhex("365f5f37365ff3")
ECHO_CONTRACT_ADDRESS = b"\x11" * 20  # 0x1111...1111
DECOMPRESSOR_ADDRESS = b"\x00" * 19 + b"\xe0"  # 0x00...00e0


class TestChain(MiningChain):
    """Simple chain for testing."""

    vm_configuration = ((0, PragueVM),)


def create_test_evm():
    """Create a test EVM with echo contract deployed."""
    db = AtomicDB()
    chain = TestChain.from_genesis(
        db,
        {
            "difficulty": 0,
            "gas_limit": constants.GENESIS_GAS_LIMIT,
            "timestamp": 0,
            "coinbase": constants.ZERO_ADDRESS,
            "extra_data": constants.GENESIS_EXTRA_DATA,
            "nonce": b"\x00" * 8,  # Must be 8 zero bytes for Prague
        },
    )

    return chain


def execute_call_with_state_override(
    chain: TestChain,
    to: bytes,
    data: bytes,
    code_override: dict[bytes, bytes] | None = None,
) -> tuple[bytes, int]:
    """
    Execute a call with optional state override (code at decompressor address).

    Returns (return_data, gas_used).
    """
    vm = chain.get_vm()

    # Deploy echo contract
    vm.state.set_code(ECHO_CONTRACT_ADDRESS, ECHO_CONTRACT_BYTECODE)

    # Apply state overrides if provided
    if code_override:
        for addr, code in code_override.items():
            vm.state.set_code(addr, code)

    sender = b"\xaa" * 20

    # Give sender some balance
    vm.state.set_balance(sender, 10**18)

    # Execute the call using Message and TransactionContext
    from eth.vm.message import Message
    from eth.vm.transaction_context import BaseTransactionContext

    message = Message(
        to=to,
        sender=sender,
        value=0,
        data=data,
        code=vm.state.get_code(to),
        gas=100_000_000,  # High gas limit for complex JIT bytecode
    )

    tx_context = BaseTransactionContext(
        origin=sender,
        gas_price=1,
    )

    # Get computation and manually execute it
    computation = vm.state.computation_class(
        state=vm.state,
        message=message,
        transaction_context=tx_context,
    )

    # Apply the computation to actually run the EVM code
    computation = computation.apply_computation(
        vm.state,
        message,
        tx_context,
    )

    if computation.is_error:
        raise RuntimeError(f"EVM execution error: {computation.error}")

    gas_used = computation.get_gas_used()
    return_data = computation.output

    return bytes(return_data), gas_used


def hex_to_bytes(hex_str: str) -> bytes:
    """Convert hex string to bytes."""
    hex_str = hex_str.replace("0x", "").replace("0X", "")
    if len(hex_str) % 2:
        hex_str = "0" + hex_str
    return bytes.fromhex(hex_str)


def bytes_to_hex(data: bytes) -> str:
    """Convert bytes to hex string with 0x prefix."""
    return "0x" + data.hex()
