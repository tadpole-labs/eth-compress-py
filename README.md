# ethcompress

Calldata compression for eth_call. For calls that do not depend on the caller or available gas, build and execute compressed calls without changing your decode logic (see limitations below). Strategies supported:

- JIT: Generate a temporary on‑chain decompressor that reconstructs calldata and forwards the call.
- FLZ: FastLZ variant used by Solady (LZ77‑style) with a tiny forwarder.
- CD: Calldata run‑length encoding (00/FF runs) with a tiny forwarder.

The library auto‑selects when helpful and can retry failed compressed requests as vanilla calls.

Decompressor installs are done via eth_call state override at a fixed address:
`0x00000000000000000000000000000000000000e0`.


## Quick Start

### Compress a single call (raw calldata)

```python
from web3 import Web3
from ethcompress import compress_eth_call

# Create a Web3 client
w3 = Web3(Web3.HTTPProvider("https://your.rpc.url"))

# to: destination contract; data_hex: 0x-prefixed calldata
cc = compress_eth_call(to, data_hex, alg="auto", min_size=800)
raw = cc.execute(w3)  # returns 0x-hex bytes

# Decode with your ABI
block_number, return_data = w3.codec.decode(["uint256", "bytes[]"], bytes.fromhex(raw[2:]))
```

### Compress from a web3py ContractFunction

```python
from ethcompress import compress_call_fn

cc = compress_call_fn(contract.functions.symbol(), alg="auto", min_size=800)
raw = cc.execute(w3) # raw output, will need to abi decode
```

### Add middleware (Web3.py)

```python
from ethcompress.middleware import CompressionMiddleware

w3.middleware_onion.add(CompressionMiddleware(
    alg="auto",        # "auto" | "jit" | "flz" | "cd"
    min_size=800,       # only compress above this many bytes
    allow_fallback=True # fall back to uncompressed on any error
))

# Existing w3.eth.call(...) keeps working; large calls get compressed
```

#### AsyncWeb3

```python
from ethcompress.middleware import AsyncCompressionMiddleware

aw3.middleware_onion.add(AsyncCompressionMiddleware(alg="auto", min_size=800))
```

#### Performance Tips

- For best performance with the middleware, use a dedicated `Web3` instance with only `CompressionMiddleware` (clear the onion and keep only compression). You can keep using `ContractFunction.call()` or call `eth_call` on pre‑encoded data — both work.

```
from ethcompress.middleware import CompressionMiddleware

# Remove all middlewares
w3.middleware_onion.clear()

# Add only compression (tweak settings as needed)
w3.middleware_onion.add(CompressionMiddleware(alg="jit", min_size=0, allow_fallback=False))
```

### Low‑level primitives

```python
from ethcompress import cd_compress, flz_compress, jit_bytecode, flz_fwd_bytecode, rle_fwd_bytecode

cd = cd_compress(data_hex)
flz = flz_compress(data_hex)
jit_code = jit_bytecode(data_hex)
flz_fwd = flz_fwd_bytecode(target_address)
cd_fwd  = rle_fwd_bytecode(target_address)
```

### Manual override call

```python
from ethcompress import compress_call_data

to2, data2, override, meta = compress_call_data(data_hex, target_address, alg="auto", min_size=800)
if meta["algo"] != "vanilla":
    resp = w3.provider.make_request("eth_call", [{"to": to2, "data": data2}, "latest", override])
else:
    resp = w3.provider.make_request("eth_call", [{"to": target_address, "data": data_hex}, "latest"])
```


## Strategy & Selection

- Threshold: by default, skip compression if calldata < 800 bytes (`min_size`).
- Auto (alg="auto"):
  - Try JIT, FLZ and CD; pick the smallest combined forwarder bytecode and compressed calldata.
  - Always validate benefit: if (code + compressed) ≥ original, use vanilla.
- Explicit `alg="jit"`, `"flz"` or `"cd"` only tries that codec, with the same benefit check.
- `sizes` and `benefit` describe binary calldata plus bytecode, not the complete JSON-RPC request. JSON keys, addresses and override framing add overhead; measure serialized request bodies when estimating network savings. Auto selection trades extra encoding CPU for smaller payloads; use an explicit codec after benchmarking your workload.

## Execution limitations

- The forwarder preserves the target call's success/failure and raw return/revert bytes, subject to sufficient gas for decompression and copying returndata.
- Forwarding adds a CALL frame: the target sees the decompressor as `msg.sender`, not the original caller, and receives less gas. `tx.origin` and the forwarded `msg.value` are preserved. Do not enable compression for caller-sensitive or gas-sensitive calls; fallback cannot detect a successful but semantically different result.
- The provider must support code state overrides and the selected block's EVM must support `PUSH0` (Shanghai or later). The fixed decompressor address must be safe to override in your execution context.
- Compression only reduces request data. It does not compress the RPC response and can increase execution gas.


## Middleware Behavior

- Intercepts only `eth_call` and only when `to`/`data` are present.
- Preserves transaction fields (`from`, `gas`, `value`, fee fields, etc.), block identifiers, existing state overrides and additional positional parameters without modifying the original request.
- Adds decompressor code to the override map. If the caller already overrides the decompressor address (case-insensitive), skips compression.
- Compression failures, transport exceptions and RPC error responses retry the exact original request once when `allow_fallback=True`. This also retries genuine contract reverts; use `False` when benchmarking or when retries are unwanted.
- With `allow_fallback=False`, exceptions propagate and RPC errors are returned to Web3's normal error handling. Calls skipped because of size, benefit or override collisions still execute normally.
- Supports Web3.py 6 and 7 middleware construction, including AsyncWeb3.


## API Reference (condensed)

- `compress_eth_call(to, data, *, alg="auto", min_size=800, allow_fallback=True) -> CompressedCall`
  - `CompressedCall.execute(w3, block="latest") -> hex`
- `compress_call_fn(fn, *, alg="auto", min_size=800, allow_fallback=True) -> CompressedCall`
- `compress_call_data(data, target, *, alg="auto", min_size=800) -> (to, data, override, meta)`
- `cd_compress(data) -> hex`, `flz_compress(data) -> hex`
- `jit_bytecode(data) -> hex`, `flz_fwd_bytecode(address) -> hex`, `rle_fwd_bytecode(address) -> hex`
- Middleware: `CompressionMiddleware(...)`, `AsyncCompressionMiddleware(...)`
