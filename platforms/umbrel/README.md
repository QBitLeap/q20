# Umbrel

The q20 app depends on its chosen Qbit Core app and owns its persistent index.
It uses the existing authenticated Core read gateway; it receives no wallet key
or Core cookie. Indexing starts automatically after installation.

After native Linux tests and image manifest verification, generate a package:

```sh
python3 scripts/package_umbrel.py /path/to/new/qbitleap-q20-main \
  --image ghcr.io/qbitleap/q20@sha256:THE_VERIFIED_REGISTRY_DIGEST
```

The generator refuses mutable tags and does not install anything. Independent
instances need distinct app IDs, ports and writable data folders. Add a verified
candidate to the QBitLeap store only after managed installation tests pass.
See [current acceptance](../../README.md#current-acceptance).
