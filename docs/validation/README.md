# q20 0.1.1 validation findings

The Linux amd64 Umbrel image passed an owner-run test against a real, isolated
Qbit Core and authenticated read gateway on November 12, 2026. The retained
[receipt](umbrel-0.1.1.json) identifies the exact native image and rules.

The run verified Mainnet genesis and rules identity, CLI/API version 0.1.1,
read authentication, absent publication routes, no Core cookie or reachable raw
RPC in q20, refusal of duplicate writers and wrong genesis, clean shutdown,
persistent index data, and recovery across Core/gateway restart. All owned test
containers, volumes and the internal network were removed successfully.

These were empty-chain fixtures with peer networking off. Height zero, initial
block download and `observedSynchronized: false` are expected. Protection must
remain unavailable in that state. This test did not install an Umbrel app,
access operational data, hold wallet keys, or connect a website.

An initial private validator expected a `q20` prefix from `--version`; the CLI
returns only `0.1.1`. The validator was corrected to match the actual packaged
CLI, while preserving strict version checking. No engine or image rebuild was
needed. The repeated owner-run validation passed in full.

The accepted desktop matrix is macOS ARM64/x64, Windows x64, Linux ARM64/x64,
and Umbrel amd64. The shared engine remains 0.1.1. This first release reuses the
exact native artifacts from the successful build workflow, with updated Umbrel
packaging credentials and validation documentation. Installation and real-chain
replay parity remain separate checks. Testnet4 activation rules remain unaccepted.

The `Accepted Umbrel image release` workflow verifies the archived native image,
checks it against the currently published Core/gateway and publishes those exact
image bytes only after the isolated checks pass. The [published image receipt](published-image-0.1.1.json) records the immutable
registry digest and successful anonymous manifest/configuration verification.
The [CI integration receipt](community-integration-0.1.1.json) records the real
Core/gateway checks against the current published dependencies. The community
catalog also runs an anonymous Docker pull and isolated integration before promotion.
