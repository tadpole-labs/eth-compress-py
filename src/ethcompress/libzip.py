from compressions.calldata import (
    cd_compress as _cd_compress,
    cd_decompress as _cd_decompress,
)
from compressions.fastlz import (
    flz_compress as _flz_compress,
    flz_decompress as _flz_decompress,
)
from compressions.utils import to_hex as _to_hex

HexLike = str | bytes


def cd_compress(data: HexLike) -> str:
    return _cd_compress(_to_hex(data))


def cd_decompress(data: HexLike) -> str:
    return _cd_decompress(_to_hex(data))


def flz_compress(data: HexLike) -> str:
    return _flz_compress(_to_hex(data))


def flz_decompress(data: HexLike) -> str:
    return _flz_decompress(_to_hex(data))


__all__ = [
    "cd_compress",
    "cd_decompress",
    "flz_compress",
    "flz_decompress",
]
