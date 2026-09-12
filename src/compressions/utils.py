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


def return_or_revert(offset: int) -> str:
    """Copy returndata, then RETURN on CALL success or REVERT with the same bytes."""
    # CALL's success flag remains on the stack underneath RETURNDATACOPY's operands.
    # PUSH4 also covers large JIT programs supplied through state overrides.
    success = offset + 13
    return f"3d5f5f3e63{success:08x}573d5ffd5b3d5ff3"


def finish_forwarder(template: str) -> str:
    """Keep decoder jump offsets stable while adding a shared return/revert epilogue."""
    # The original return sequence occupied eight bytes. Jump past the decoder instead;
    # padding is unreachable and preserves every existing absolute decoder label.
    epilogue = len(bytes.fromhex(template.format(return_code="00" * 8)))
    jump = f"61{epilogue:04x}56" + "00" * 4
    return "0x" + template.format(return_code=jump) + "5b" + return_or_revert(epilogue + 1)
