# macOS

Choose the Intel (`macos-x64`) or Apple Silicon (`macos-arm64`) archive from a
validated build. Extract it; Python is included. In Terminal:

```sh
./q20/q20 start --rpc-url http://127.0.0.1:18443 --cookie /path/to/core/.cookie
```

Use your actual Core endpoint/cookie. The dashboard opens at
http://127.0.0.1:8790. Default data: `~/Library/Application Support/q20/mainnet`.
Mainnet and custom test profiles must use separate data directories.
See the [suite README](../../README.md) for validation and acceptance limits.

## Version 0.1.1

[Apple silicon](https://github.com/QBitLeap/q20/releases/download/v0.1.1/q20-0.1.1-macos-arm64.tar.gz) · [Intel](https://github.com/QBitLeap/q20/releases/download/v0.1.1/q20-0.1.1-macos-x64.tar.gz)

The engine version is unchanged. See the shared [validation findings](../../docs/validation/README.md)
for the native platform matrix and isolated Core/gateway acceptance.
