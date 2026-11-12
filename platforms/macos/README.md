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
