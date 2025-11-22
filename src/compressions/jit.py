import math

from .utils import hex_to_bytes as _hex_to_bytes, norm_hex

MAX_128_BIT = (1 << 128) - 1
MASK32 = (1 << 256) - 1


def _bytes_to_hex(data: bytes) -> str:
    return data.hex()


def _uint8_to_hex(arr: list[int]) -> str:
    return "".join(f"{b:02x}" for b in arr)


def jit_bytecode(calldata: str) -> str:
    return _jit_decompressor("0x" + norm_hex(calldata))


def _jit_decompressor(calldata: str) -> str:
    hex_data = norm_hex(calldata)
    original = _hex_to_bytes(hex_data)
    original_len = len(original)

    # Right-align the 4-byte selector in the first 32-byte slot to improve alignment.
    if original_len >= 4:
        padding = 32 - 4
        buf_bytes = bytes([0] * padding) + original[:4] + original[4:]
    else:
        padding = 0
        buf_bytes = original
    buf = list(buf_bytes)
    n = len(buf)

    ops: list[int] = []
    data: list[list[int] | None] = []
    stack: list[int] = []
    tracked_mem_size = 0
    mem: dict[int, int] = {}

    def get_stack_idx(val: int) -> int:
        try:
            idx = len(stack) - 1 - stack[::-1].index(val)
        except ValueError:
            return -1
        return len(stack) - 1 - idx

    op_freq: dict[int, int] = {}
    data_freq: dict[tuple[int, ...] | None, int] = {}
    stack_freq: dict[int, int] = {}
    word_cache: dict[str, int] = {}
    word_cache_cost: dict[str, int] = {}

    def round_up_32(x: int) -> int:
        return (x + 31) & ~31

    push_counter = 0
    stack_cnt: dict[int, int] = {}

    def ctr(m: dict, k, delta: int) -> None:
        m[k] = m.get(k, 0) + delta

    def inc(m: dict, k) -> None:
        ctr(m, k, 1)

    def dec(m: dict, k) -> None:
        ctr(m, k, -1)

    def pop2() -> tuple[int, int]:
        a = stack.pop()
        b = stack.pop()
        return a, b

    def push_op(op: int) -> None:
        ops.append(op)
        inc(op_freq, op)

    def push_d(d: list[int] | None) -> None:
        data.append(d if d else None)
        inc(data_freq, tuple(d) if d else None)

    def push_s(v: int, freq: int = 1) -> None:
        nonlocal push_counter
        stack.append(v)
        ctr(stack_freq, v, freq)
        push_counter += 1
        stack_cnt[v] = push_counter

    def track_mem(offset: int, size: int) -> None:
        nonlocal tracked_mem_size
        tracked_mem_size = round_up_32(offset + size)

    def is_in_stack(w):
        return w in stack or w == 0xE0 or w == 32

    def add_op(op: int, imm: list[int] | None = None) -> None:
        nonlocal tracked_mem_size
        if op == 0x36:    # CALLDATASIZE
            push_s(32)
        elif op == 0x59:  # MSIZE
            push_s(tracked_mem_size, 0)
        elif op == 0x1B:  # SHL
            shift, val = pop2()
            if ops and ops[-1] == 144:
                ops.pop()
                data.pop()
                shift, val = val, shift
            push_s((val << shift) & MASK32)
        elif op == 0x17:  # OR
            a, b = pop2()
            if ops and ops[-1] == 144:
                ops.pop()
                data.pop()
            push_s((a | b) & MASK32)
        elif (0x60 <= op <= 0x7F) or op == 0x5F:  # PUSHx/PUSH0
            v = 0
            for b in imm or []:
                v = ((v << 8) | b) & MASK32
            if v == 224:
                push_s(v)
                push_op(0x30)  # ADDRESS
                push_d(None)
                return
            idx = get_stack_idx(v)
            if idx != -1 and op != 0x5F:
                last = stack_freq.get(v, 0) == 0
                if idx == 0 and last:
                    dec(stack_freq, v)
                    return

                if idx == 1 and last:
                    push_op(144)  # SWAP2
                    a, b = pop2()
                    stack.append(b)
                    stack.append(a)
                    push_d(None)
                    dec(stack_freq, v)
                    return

                push_s(v, -1)
                push_op(0x80 + idx)
                push_d(None)
                return
            push_s(v)        
        elif op == 0x51:  # MLOAD
            k = int(stack.pop())
            push_s(mem.get(k, 0))
        elif op == 0x52:  # MSTORE
            offset, value = pop2()
            k = int(offset)
            mem[k] = value & MASK32
            track_mem(k, 32)
        elif op == 0x53:  # MSTORE8
            offset, _value = pop2()
            track_mem(int(offset), 1)
        elif op == 0xF3:  # RETURN
            _ = pop2()
        push_op(op)
        push_d(imm or None)

    def op(opcode: int) -> None:
        add_op(opcode)

    def push_n(value: int) -> None:
        if value > 0 and value == tracked_mem_size:
            add_op(0x59)
            return
        if value == 0:
            add_op(0x5F)
            return
        if value == 32:
            add_op(0x36)
            return
        v = int(value)
        bytes_be: list[int] = []
        while v:
            bytes_be.insert(0, v & 0xFF)
            v >>= 8
        add_op(0x5F + len(bytes_be), bytes_be)

    def push_b(b: bytes) -> None:
        add_op(0x5F + len(b), list(b))

    def cnt_words(big_hex: str, word_hex: str) -> int:
        # Count occurrences (non-overlapping is fine for 64-char words)
        return big_hex.count(word_hex)

    def est_shl_cost(seg: list[tuple[int, int]]) -> int:
        cost = 0
        first = True
        for s, e in seg:
            cost += 1 + (e - s + 1)  # PUSH segLen bytes
            suffix = 31 - e
            if suffix > 0:
                cost += 1 + 1 + 1  # PUSH1 + shift byte + SHL
            if not first:
                cost += 1  # OR
            first = False
        return cost

    class PlanStep:
        __slots__ = ("t", "v", "b", "o")

        def __init__(
            self,
            t: str,
            v: int | None = None,
            b: bytes | None = None,
            o: int | None = None,
        ):
            self.t = t
            self.v = v
            self.b = b
            self.o = o

    plan: list[PlanStep] = []

    def emit_push_n(v: int) -> None:
        plan.append(PlanStep("num", v=v))
        push_n(v)

    def emit_push_b(b: bytes) -> None:
        plan.append(PlanStep("bytes", b=b))
        push_b(b)

    def emit_op(o: int) -> None:
        plan.append(PlanStep("op", o=o))
        op(o)

    push_n(1)
    for base in range(0, n, 32):
        word = bytearray(32)
        copy_end = min(base + 32, n)
        word[0 : (copy_end - base)] = bytes(buf[base:copy_end])

        seg: list[tuple[int, int]] = []
        i = 0
        while i < 32:
            while i < 32 and word[i] == 0:
                i += 1
            if i >= 32:
                break
            s = i
            while i < 32 and word[i] != 0:
                i += 1
            seg.append((s, i - 1))

        if not seg:
            continue



        literal = bytes(word[seg[0][0] : 32])
        literal_cost = 1 + len(literal)

        base_bytes = math.ceil(math.log2(base + 1) / 8) if base > 0 else 1
        word_hex = _bytes_to_hex(bytes(word))

        if literal_cost > 8:
            if word_hex in word_cache:
                if literal_cost > word_cache_cost.get(word_hex, 0) + base_bytes:
                    emit_push_n(word_cache[word_hex])
                    emit_op(0x51)  # MLOAD
                    emit_push_n(base)
                    emit_op(0x52)  # MSTORE
                    continue
            elif word_cache_cost.get(word_hex, 0) != -1:
                reuse_cost = base_bytes + 3
                freq = cnt_words(hex_data, word_hex)
                word_cache_cost[word_hex] = reuse_cost if (freq * 32) > (freq * reuse_cost) else -1
                word_cache[word_hex] = base
        byte8s = all(s == e for s, e in seg)
        if is_in_stack(literal):
            emit_push_b(literal)
        elif byte8s:
            for s, _e in seg:
                emit_push_n(word[s])
                emit_push_n(base + s)
                emit_op(0x53)  # MSTORE8
            continue
        elif literal_cost <= est_shl_cost(seg):
            emit_push_b(literal)
        else:
            first = True
            for s, e in seg:
                suffix0s = 31 - e
                emit_push_b(bytes(word[s : e + 1]))
                if suffix0s > 0:
                    emit_push_n(suffix0s * 8)
                    emit_op(0x1B)  # SHL
                if not first:
                    emit_op(0x17)  # OR
                first = False
        emit_push_n(base)
        emit_op(0x52)  # MSTORE

    ops = []
    data = []
    stack = []
    tracked_mem_size = 0
    mem = {}

    # Pre 2nd pass: push most frequent literals into stack
    pre_candidates = [
        (val, freq)
        for val, freq in stack_freq.items()
        if (isinstance(val, int) and (freq > 1) and (val != 32) and (val != 224) and (val <= MAX_128_BIT)) 
    ]
    pre_candidates.sort(key=lambda x: stack_cnt.get(x[0], 0), reverse=True)

    for val, _ in pre_candidates[:13]:
        push_n(val)
        
    push_n(1)
    # Second pass: emit ops based on plan
    for step in plan:
        if step.t == "num":
            assert step.v is not None
            push_n(int(step.v))
        elif step.t == "bytes":
            push_b(step.b if isinstance(step.b, bytes | bytearray) else b"")
        elif step.t == "op":
            assert step.o is not None
            op(int(step.o))

    # CALL trampoline stack: [retSize, retOffset, argsSize, argsOffset, value, address, gas]
    op(0x5F)  # PUSH0 (retSize)
    op(0x5F)  # PUSH0 (retOffset)
    push_n(original_len)  # argsSize = original length
    push_n(padding)  # argsOffset = leading padding bytes

    # Flatten ops + immediates
    out: list[int] = []
    for i, opcode in enumerate(ops):
        out.append(opcode)
        if 0x60 <= opcode <= 0x7F and data[i]:
            out.extend(data[i] or [])

    # Epilogue: CALLVALUE; PUSH0 CALLDATALOAD; GAS; CALL; POP; RETURNDATACOPY/RETURN
    suffix = bytes.fromhex("345f355af13d5f5f3e3d5ff3")
    return "0x" + _uint8_to_hex(out) + suffix.hex()
