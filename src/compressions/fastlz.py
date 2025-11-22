from .utils import bytes_to_hex as _bytes_to_hex, hex_string as _hex_string, norm_hex

"""
Library for compressing and decompressing bytes.

Reference:
    - Solady (https://github.com/vectorized/solady/blob/main/src/utils/LibZip.sol)
    - FastLZ by ariya (https://github.com/ariya/FastLZ)
"""

def flz_compress(data: str) -> str:
    """Compresses hex encoded data with the FastLZ variant used by Solady.

    Direct, literal port of solady.js LibZip.flzCompress for bit-exact behavior.
    """
    hex_data = _hex_string(data)
    # Work with Python lists of ints for close parity with JS arrays
    ib = list(bytes.fromhex(hex_data))
    n = len(ib)
    b = n - 4

    # Early out for tiny inputs (emit as literals)
    if n <= 0:
        return _bytes_to_hex(b"")

    ob = []  # output bytes as ints
    ht = [0] * 8192  # hash table indices

    a = 0
    i = 2

    def u24(idx: int) -> int:
        return ib[idx] | (ib[idx + 1] << 8) | (ib[idx + 2] << 16)

    def hash32(x: int) -> int:
        return ((2654435769 * (x & 0xFFFFFFFF)) & 0xFFFFFFFF) >> 19 & 8191

    def literals(r: int, s: int) -> None:
        while r >= 32:
            ob.append(31)
            for _ in range(32):
                ob.append(ib[s])
                s += 1
            r -= 32
        if r:
            ob.append(r - 1)
            for _ in range(r):
                ob.append(ib[s])
                s += 1

    while i < b - 9:
        # do { ... } while (i < b - 9 && i++ && s != c)
        while True:
            s = u24(i)
            h = hash32(s)
            r = ht[h] or 0
            ht[h] = i
            d = i - r
            c = u24(r) if d < 8192 else 0x1000000
            i += 1
            if not (i < b - 9 and s != c):
                break
        if i >= b - 9:
            break
        i -= 1
        if i > a:
            literals(i - a, a)
        # Extend match length with exact JS semantics:
        # for (match_len = 0, p = r + 3, q = i + 3, e = b - q; match_len < e; match_len++) e *= ib[p + match_len] === ib[q + match_len];
        match_len = 0
        p = r + 3
        q = i + 3
        e = b - q
        while match_len < e:
            e = e * (1 if ib[p + match_len] == ib[q + match_len] else 0)
            match_len += 1
        i += match_len
        d -= 1
        while match_len > 262:
            ob.append(224 + (d >> 8))
            ob.append(253)
            ob.append(d & 255)
            match_len -= 262
        if match_len < 7:
            ob.append((match_len << 5) + (d >> 8))
            ob.append(d & 255)
        else:
            ob.append(224 + (d >> 8))
            ob.append(match_len - 7)
            ob.append(d & 255)
        # Update ht for next 2 positions (exactly as JS)
        if i + 2 < n:
            ht[hash32(u24(i))] = i
        i += 1
        if i + 2 < n:
            ht[hash32(u24(i))] = i
        i += 1
        a = i

    # Emit trailing literals
    literals(b + 4 - a, a)

    return _bytes_to_hex(bytes(ob))


def flz_decompress(data: str) -> str:
    """Decompresses hex encoded data with the FastLZ variant used by Solady.

    Mirrors the JS implementation in solady.js (LibZip.flzDecompress).
    Returns a lower-case hex string with 0x prefix.
    """
    hex_data = _hex_string(data)
    ib = bytes.fromhex(hex_data)
    i = 0
    ob = bytearray()

    n = len(ib)
    while i < n:
        t = ib[i] >> 5
        if t == 0:
            lit_len = 1 + ib[i]
            i += 1
            ob.extend(ib[i : i + lit_len])
            i += lit_len
        else:
            # Note: eval t < 7 first to compute f and match_len correctly
            # f = 256 * (ib[i] & 31) + ib[i + 2 - (t = t < 7)]
            if t < 7:
                f = 256 * (ib[i] & 31) + ib[i + 1]
                match_len = 2 + (ib[i] >> 5)
                i += 2
            else:
                f = 256 * (ib[i] & 31) + ib[i + 2]
                match_len = 9 + ib[i + 1]
                i += 3
            r = len(ob) - f - 1
            if r < 0:
                raise ValueError("Invalid back-reference during decompression.")
            # copy match_len bytes from r
            for _ in range(match_len):
                ob.append(ob[r])
                r += 1

    return _bytes_to_hex(bytes(ob))


def flz_fwd_bytecode(address: str) -> str:
    return (
        "0x365f73"
        + norm_hex(address)
        + "815b838110602f575f80848134865af1503d5f803e3d5ff35b803590815f1a8060051c908115609857600190600783149285831a6007018118840218600201948383011a90601f1660081b0101808603906020811860208211021890815f5b80830151818a015201858110609257505050600201019201916018565b82906075565b6001929350829150019101925f5b82811060b3575001916018565b85851060c1575b60010160a6565b936001818192355f1a878501530194905060ba56"
    )


__all__ = ["flz_compress", "flz_decompress", "flz_fwd_bytecode"]
