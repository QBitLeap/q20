# Umbrel

The q20 app depends on its chosen Qbit Core app and owns its persistent index.
It uses the existing authenticated Core read gateway; it receives no wallet key
or Core cookie. Indexing starts automatically after installation.

For installation, refresh the existing [QBitLeap community app store](https://github.com/QBitLeap/umbrel-app-store)
and install **q20 Indexer 0.1.1**. Keep Qbit Core running; indexing starts
automatically. No terminal setup or website connection is required.

For maintainers generating a separate candidate after native tests:

```sh
python3 scripts/package_umbrel.py /path/to/new/qbitleap-q20-main \
  --image ghcr.io/qbitleap/q20@sha256:THE_VERIFIED_REGISTRY_DIGEST
```

The generator refuses mutable tags and does not install anything. Independent
instances need distinct app IDs, ports and writable data folders. Add a candidate to the QBitLeap store only after native integration, exact-image
verification and anonymous pull checks pass. Verify managed installation after
installing the resulting community package.
See [current acceptance](../../README.md#current-acceptance).

The initial 0.1.1 image passed the real Core/gateway fixture. See
[the validation findings](../../docs/validation/README.md). The community store
is https://github.com/QBitLeap/umbrel-app-store. q20 is a standalone Mainnet app;
no website connection or Testnet4 rules are required to run it.
