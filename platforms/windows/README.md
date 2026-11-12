# Windows

Extract a validated `windows-x64` archive. Python is included. In PowerShell:

```powershell
.\q20\q20.exe start --rpc-url http://127.0.0.1:18443 --cookie C:\path\to\core\.cookie
```

Use your actual Core endpoint/cookie. Dashboard: http://127.0.0.1:8790.
Default data: `%LOCALAPPDATA%\q20\mainnet`. Custom test profiles need a
separate data directory. See the [suite README](../../README.md) for acceptance.

## Version 0.1.1

[x64](https://github.com/QBitLeap/q20/releases/download/v0.1.1/q20-0.1.1-windows-x64.zip)

The engine version is unchanged. See the shared [validation findings](../../docs/validation/README.md)
for the native platform matrix and isolated Core/gateway acceptance.
