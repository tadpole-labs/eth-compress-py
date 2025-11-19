# ethcompress

Calldata compression for eth_call. Build and execute compressed calls that return byte‑identical results, without changing your decode logic. Strategies supported:

- JIT: Generate a temporary on‑chain decompressor that reconstructs calldata and forwards the call.
- FLZ: FastLZ variant used by Solady (LZ77‑style) with a tiny forwarder.
- CD: Calldata run‑length encoding (00/FF runs) with a tiny forwarder.

The library auto‑selects when helpful and safely falls back to vanilla.

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
  - If original size ≥ 2096 bytes: prefer JIT (no FLZ/CD trials).
  - Else: compute FLZ and CD once, pick the smaller compressed stream.
  - Always validate benefit: if (code + compressed) ≥ original, use vanilla.

All strategies are transparent: the decompressor forwards to the real target and returns the same bytes as a vanilla call.


## Middleware Behavior

- Intercepts only `eth_call` and only when `to`/`data` are present.
- Builds compressed call and state override; merges with any existing override map.
- On failure, returns vanilla result when `allow_fallback=True`.


## API Reference (condensed)

- `compress_eth_call(to, data, *, alg="auto", min_size=800, allow_fallback=True) -> CompressedCall`
  - `CompressedCall.execute(w3, block="latest") -> hex`
- `compress_call_fn(fn, *, alg="auto", min_size=800, allow_fallback=True) -> CompressedCall`
- `compress_call_data(data, target, *, alg="auto", min_size=800) -> (to, data, override, meta)`
- `cd_compress(data) -> hex`, `flz_compress(data) -> hex`
- `jit_bytecode(data) -> hex`, `flz_fwd_bytecode(address) -> hex`, `rle_fwd_bytecode(address) -> hex`
- Middleware: `CompressionMiddleware(...)`, `AsyncCompressionMiddleware(...)`
