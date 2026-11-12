# q20

Independent QBIT-20 indexer for **[macOS](platforms/macos/README.md),
[Windows](platforms/windows/README.md), [Linux](platforms/linux/README.md), and
[Umbrel](platforms/umbrel/README.md)**. Version 0.1.1.

One engine examines the first OP_RETURN in every confirmed transaction, separates
JSON syntax from protocol validity, and maintains address balances and bound
listing outputs in block order. It owns its index and follows a selected Qbit
Core. It holds no wallet keys and does not sign or broadcast transactions.

## Downloads

| Platform | q20 0.1.1 |
| --- | --- |
| macOS | [Apple silicon](https://github.com/QBitLeap/q20/releases/download/v0.1.1/q20-0.1.1-macos-arm64.tar.gz) · [Intel](https://github.com/QBitLeap/q20/releases/download/v0.1.1/q20-0.1.1-macos-x64.tar.gz) |
| Windows | [x64](https://github.com/QBitLeap/q20/releases/download/v0.1.1/q20-0.1.1-windows-x64.zip) |
| Linux | [ARM64](https://github.com/QBitLeap/q20/releases/download/v0.1.1/q20-0.1.1-linux-arm64.tar.gz) · [x64](https://github.com/QBitLeap/q20/releases/download/v0.1.1/q20-0.1.1-linux-x64.tar.gz) |
| Umbrel | [QBitLeap community app store](https://github.com/QBitLeap/umbrel-app-store) · Mainnet package |

For Umbrel, refresh the existing QBitLeap community store and install **q20 Indexer 0.1.1**.
Keep Qbit Core running; Mainnet indexing starts automatically.

Use the release checksums before running downloaded artifacts. Native package
checks, isolated Core integration, managed installation and real-chain parity
are recorded separately in the [validation findings](docs/validation/README.md).

## Current acceptance

The 0.1.1 native suite passed macOS ARM64/x64, Windows x64, Linux ARM64/x64
and Umbrel amd64 builds. The exact Umbrel image also passed the owner-run real
Core/read-gateway fixture, including auth, isolation, restart and cleanup. See
[validation findings](docs/validation/README.md). Managed Umbrel installation
and real-chain replay parity remain separate acceptance checks.
Do not rely on q20 alone to approve real token purchases until replay parity has
been checked against an independent implementation.

The pinned default is Mainnet. The published sources do not state every
Testnet4 activation height. A Testnet4 rules profile is therefore **not shipped
as accepted**; using Mainnet heights or making every extension active at genesis
would invent token history. The suite includes Testnet4 icon variants for the
matching packages once those parameters are confirmed. A custom reviewed profile
can be supplied with `--rules` and must use its own data directory.

## Validation

The [QBIT-20 specification](https://qrc.market/spec) and
[listing extensions](https://qrc.market/spec/listings) define these distinctions:

- Non-UTF-8 data, malformed JSON, arrays and other protocol markers create no
  token state. Text is decoded as data and never executed or rendered as HTML.
- Recognized records require exact case, permitted ticker length at that block,
  decimal **strings**, positive amounts and supported operations. Amounts use
  integers, never floating point. Unknown fields are ignored where required.
  Iterative container parsing handles deeply nested unknown fields without a
  Python recursion failure; large integer strings retain their exact value.
- Ordinary JSON duplicate keys use the last decoded key; listing binds reject
  duplicates anywhere, including escaped spellings and nested objects. A failed
  v1-3 bind can still be an ordinary transfer. A failed transfer to the activated
  v5 sink is ignored without debiting its sender.
- First valid deploy wins. Mints follow opening height, remaining supply, fixed
  amount, per-address/per-block and lifetime limits, and the per-token block cap.
  Mint-lock signatures use Qbit's SLH-DSA-SHA2-128s-bounded30 verifier.
- Listing versions 1/2/3 and corrected version 5 releases are height dependent.
  Partial sales recognize the transaction's shape; only the specified buy leaf
  rebinds the unsold lots. Buy-ticket witnesses can change the credited buyer.
- Missing prevouts, required witnesses or signature verification stop the block
  atomically. They are not classified as invalid messages or guessed past.
- Block changes are journaled and undone on a reorg. A network/rules fingerprint
  binds each database to one interpretation. Changing rules requires a new index.

The published listing document still describes the Mainnet buy-ticket height as
pending. The marketplace's captured `/api/v1/status` explicitly states 163900;
the pinned profile uses that stated height. Source hashes and observation identity
are retained in `dependencies.lock.json`.

## Spend protection

Ordinary QBIT-20 balances belong to **addresses**, rather than inscription sats.
Spending an unrelated QBT output does not itself send that address's token balance.
Listing escrow outputs are different: spending one releases its bound tokens.

`POST /v1/protection` identifies those protected outpoints. It requires a fresh
Core genesis/network/tip proof, a matching index snapshot and confirmed unspent
outputs. If these cannot be established, it returns HTTP 503, never a permissive
empty list. A compatible wallet/site must call it before selecting funds and
again before publishing, and combine the result with LEAP/PINS/qord protection.
Installing an indexer does **not** change an external wallet's coin selection.
The BuildIt website has not yet been connected to this API.

## Run from source

Python 3.11+, a C compiler, and a running Qbit Core with `txindex=1` are needed.
Vendored crypto source is pinned and included; runtime operation downloads no
crypto code or protocol updates.

```sh
python3 scripts/build_crypto.py
python3 -m unittest discover -s tests -v
python3 -m q20 start --rpc-url http://127.0.0.1:18443 --cookie /path/to/core/.cookie
```

Choose the actual loopback RPC endpoint and private cookie of your Core.
q20 starts indexing automatically and serves its dashboard at
`http://127.0.0.1:8790`. It does not start another Core or change its settings.
At tip it checks once a minute, without re-reading old blocks or writing an
unchanged database. The dashboard refresh defaults to one minute, accepts a
longer whole-minute interval, and pauses on hidden pages.

```sh
python3 -m q20 inspect message.json --height 171555
```

Inspection reports syntax/schema status. Only a confirmed block-order replay
can establish a message's effect on token state.

## Read API

The API uses HTTP Basic `reader:<per-installation token>`. Native installations
create `read-api.token` in their data directory; Umbrel derives its credential
per installation. No default password is published.

| Route | Result |
| --- | --- |
| `GET /status` | Dashboard counts, network, height and last observed status |
| `GET /v1/status` | Authenticated status |
| `GET /v1/messages?limit=100&offset=0` | Classification, reason, size/hash and transaction/block identity; full raw payload for recognized QBIT-20 records |
| `GET /v1/tokens` | Token deploys, mint limits and minted amounts |
| `GET /v1/balances/<address>` | Address balances at the returned snapshot height |
| `GET /v1/bound` | Current bound listing outputs and their original terms |
| `POST /v1/protection` | Fresh protection decision for `{"coins":[{"txid":"…","vout":1}]}` |

q20's state digest has its own documented serialization (sorted state rows,
canonical JSON and SHA-256). It is **not** claimed to equal the marketplace's
unspecified digest format. Compare balances, listings and events at the same
block hash instead.

## Build the four-platform suite

`Desktop and Umbrel checks` is a manually dispatched workflow. It tests native
macOS Intel/Apple Silicon, Windows x64 and Linux x64/ARM64 runners, then extracts
and checks each archive. The Linux job also builds and tests the Umbrel Docker
image. It uploads build artifacts; it does not publish releases or images.

```sh
python3 -m pip install PyInstaller==6.20.0
python3 scripts/package_desktop.py --output /path/to/new/artifacts
```

Archives include the Python runtime, verifier, dashboard, icons, notices and
source dependency identity. They are built on their target OS. Cross-platform
source checks are not called native execution. Packages are not code-signed or
notarized. The source and base image are pinned; apt/compiler resolution means
bit-for-bit reproducibility is not claimed.

MIT application license. Dependency licenses are retained under `third_party/`.
