# q20 workspace

This repository is the independent QBitLeap q20 suite for macOS, Windows,
Linux and Umbrel. Keep protocol/index state separate from LEAP, PINS, qord,
the website and the private Media Cache. Do not start a Core daemon, access
wallet keys or broadcast transactions as part of routine tests.

Use repository-local Git identity `LEAP
<306298260+QLeapBit@users.noreply.github.com>`.

Never infer token validity from JSON syntax alone. Preserve the original
payload and transaction/block/network identity. Rule activation heights are
immutable for a database; unknown/missing source data must stop the block
atomically. QBIT-20 address balances are distinct from bound listing outputs.
The protection API must establish a fresh canonical Core/index match and must
return unavailable when it cannot, rather than reporting an empty protection set.

The published sources do not establish every Testnet4 activation height.
Do not invent an accepted Testnet4 profile. See README current acceptance.
The suite's Testnet4 icons are artwork, not evidence of supported token history.

Run `python scripts/build_crypto.py`, `python -m unittest discover -s tests -v`,
`python checks/smoke_process.py` and `node --test checks/dashboard.test.cjs`.
Package each OS on that native OS. The manual build workflow produces artifacts
without publishing releases/images. Managed Umbrel installation and real-chain
parity must remain separate acceptance gates. No wallet integration is implied
merely by installing this indexer.
