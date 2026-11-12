# Linux

Extract a validated `linux-x64` or `linux-arm64` archive. Python is included:

```sh
./q20/q20 start --rpc-url http://127.0.0.1:18443 --cookie /path/to/core/.cookie
```

Use your actual Core endpoint/cookie. Dashboard: http://127.0.0.1:8790.
Data: `$XDG_DATA_HOME/q20/mainnet`, defaulting to `~/.local/share/q20/mainnet`.
See the [suite README](../../README.md) for validation and acceptance limits.

## Version 0.1.1

[ARM64](https://github.com/QBitLeap/q20/releases/download/v0.1.1/q20-0.1.1-linux-arm64.tar.gz) · [x64](https://github.com/QBitLeap/q20/releases/download/v0.1.1/q20-0.1.1-linux-x64.tar.gz)

The engine version is unchanged. See the shared [validation findings](../../docs/validation/README.md)
for the native platform matrix and isolated Core/gateway acceptance.
