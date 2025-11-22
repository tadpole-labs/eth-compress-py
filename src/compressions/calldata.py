from .utils import hex_string as _hex_string, norm_hex

"""
Library for compressing and decompressing bytes.

Reference:
    - Solady (https://github.com/vectorized/solady/blob/main/src/utils/LibZip.sol)
    - Calldata compression by clabby (https://github.com/clabby/op-kompressor)
"""

def _parse_byte(s: str, i: int) -> int:
    return int(s[i : i + 2], 16)


def cd_compress(data: str) -> str:
    """Compresses hex encoded calldata (Solady compatible).

    Returns a lower-case hex string with 0x prefix.
    Optimized to operate on bytes and accumulate into a bytearray.
    """
    hex_data = _hex_string(data)
    ib = bytes.fromhex(hex_data)

    out = bytearray()
    out_len = 0  # track length to avoid repeated len(out) calls
    z = 0  # run length of 0x00
    y = 0  # run length of 0xff

    out_append = out.append

    def push_byte(b: int) -> None:
        nonlocal out_len
        if out_len < 4:
            out_append((b ^ 0xFF) & 0xFF)
        else:
            out_append(b & 0xFF)
        out_len += 1

    i = 0
    n = len(ib)
    while i < n:
        c = ib[i]
        i += 1
        if c == 0x00:
            if y:
                # rle(1, y)
                push_byte(0x00)
                push_byte((y - 1) + 0x80)
                y = 0
            z += 1
            if z == 0x80:
                # rle(0, 0x80)
                push_byte(0x00)
                push_byte(0x80 - 1)
                z = 0
            continue
        if c == 0xFF:
            if z:
                # rle(0, z)
                push_byte(0x00)
                push_byte(z - 1)
                z = 0
            y += 1
            if y == 0x20:
                # rle(1, 0x20)
                push_byte(0x00)
                push_byte((0x20 - 1) + 0x80)
                y = 0
            continue
        # literal byte
        if y:
            push_byte(0x00)
            push_byte((y - 1) + 0x80)
            y = 0
        if z:
            push_byte(0x00)
            push_byte(z - 1)
            z = 0
        push_byte(c)

    # flush any remaining runs
    if y:
        push_byte(0x00)
        push_byte((y - 1) + 0x80)
    if z:
        push_byte(0x00)
        push_byte(z - 1)

    return "0x" + out.hex()


def cd_decompress(data: str) -> str:
    """Decompresses hex encoded calldata (Solady compatible).

    Returns a lower-case hex string with 0x prefix.
    Optimized to operate on bytes and accumulate into a bytearray.
    """
    hex_data = _hex_string(data)
    comp = bytes.fromhex(hex_data)

    out = bytearray()
    out_extend = out.extend
    out_append = out.append

    pos = 0
    n = len(comp)

    while pos < n:
        b = comp[pos]
        if pos < 4:
            b ^= 0xFF
        pos += 1
        c = b
        if c == 0x00:
            if pos >= n:
                raise ValueError("Unexpected end of data during decompression.")
            b2 = comp[pos]
            if pos < 4:
                b2 ^= 0xFF
            pos += 1
            s = (b2 & 0x7F) + 1
            if b2 >> 7:
                # emit up to 32 bytes of 0xFF (the rest 0x00), but JS encodes exactly s bytes where for j<32 => 0xff else 0x00
                if s <= 32:
                    out_extend(b"\xff" * s)
                else:
                    out_extend(b"\xff" * 32)
                    out_extend(b"\x00" * (s - 32))
            else:
                out_extend(b"\x00" * s)
        else:
            out_append(c)

    return "0x" + out.hex()


def rle_fwd_bytecode(address: str) -> str:
    return (
        "0x5f5f5b368110602d575f8083813473"
        + norm_hex(address)
        + "5af1503d5f803e3d5ff35b600180820192909160031981019035185f1a8015604c57815301906002565b505f19815282820192607f9060031981019035185f1a818111156072575b160101906002565b838101368437606a56"
    )


__all__ = ["cd_compress", "cd_decompress", "rle_fwd_bytecode"]
