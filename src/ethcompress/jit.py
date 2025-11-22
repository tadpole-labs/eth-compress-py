from compressions.calldata import rle_fwd_bytecode as _rle_fwd_bytecode
from compressions.fastlz import flz_fwd_bytecode as _flz_fwd_bytecode
from compressions.jit import jit_bytecode as _jit_bytecode
from compressions.utils import to_hex as _to_hex

HexLike = str | bytes


def jit_bytecode(data: HexLike) -> str:
    return _jit_bytecode(_to_hex(data))


def flz_fwd_bytecode(address: str) -> str:
    return _flz_fwd_bytecode(address)


def rle_fwd_bytecode(address: str) -> str:
    return _rle_fwd_bytecode(address)


__all__ = ["flz_fwd_bytecode", "jit_bytecode", "rle_fwd_bytecode"]
