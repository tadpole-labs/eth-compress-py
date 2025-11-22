import os
import time

from ethcompress import jit_bytecode


def _hex(b: bytes) -> str:
    return "0x" + b.hex()


def test_jit_suffix_and_nonempty():
    data = os.urandom(1024)
    h = _hex(data)
    t0 = time.perf_counter()
    bc = jit_bytecode(h)
    t1 = time.perf_counter()
    assert bc.startswith("0x")
    assert len(bc) > 2
    # Known trailer from implementation (JIT epilogue)
    assert bc.endswith("345f355af13d5f5f3e3d5ff3")
    print(f"JIT bytecode: bytes={(len(bc)-2)//2} gen_ms={(t1-t0)*1000:.3f}")
