# Windows

Extract a validated `windows-x64` archive. Python is included. In PowerShell:

```powershell
.\q20\q20.exe start --rpc-url http://127.0.0.1:18443 --cookie C:\path\to\core\.cookie
```

Use your actual Core endpoint/cookie. Dashboard: http://127.0.0.1:8790.
Default data: `%LOCALAPPDATA%\q20\mainnet`. Custom test profiles need a
separate data directory. See the [suite README](../../README.md) for acceptance.
