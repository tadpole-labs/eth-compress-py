def norm_hex(hex_str: str) -> str:
    s = hex_str.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    if len(s) % 2 != 0:
        raise ValueError("Hex string length must be a multiple of 2.")
    bytes.fromhex(s)
    return s


def hex_string(data: str) -> str:
    if isinstance(data, str):
        try:
            return norm_hex(data)
        except ValueError as e:
            raise ValueError("Data must be a hex string.") from e
    raise ValueError("Data must be a hex string.")


def bytes_to_hex(data: bytes) -> str:
    return "0x" + data.hex()


def hex_to_bytes(hex_str: str) -> bytes:
    return bytes.fromhex(norm_hex(hex_str))


def to_hex(data: str | bytes) -> str:
    if isinstance(data, bytes):
        return "0x" + data.hex()
    if isinstance(data, str):
        s = data.strip()
        return s if s.startswith("0x") or s.startswith("0X") else ("0x" + s)
    raise TypeError("expected hex string or bytes")
