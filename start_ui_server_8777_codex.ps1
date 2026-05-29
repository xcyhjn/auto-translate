$ErrorActionPreference = 'Stop'
Start-Transcript -Path 'D:\autosub_zh\ui_server_8777_codex_transcript.log' -Append | Out-Null
"starting $(Get-Date -Format o)" | Add-Content -LiteralPath 'D:\autosub_zh\ui_server_8777_codex_marker.log'
$env:AUTOSUB_UI_PORT = '8777'
$env:HTTP_PROXY = 'http://127.0.0.1:7890'
$env:HTTPS_PROXY = 'http://127.0.0.1:7890'
$env:PYTHONPATH = 'D:\'
Set-Location 'D:\'
& 'C:\Users\bulbel\AppData\Local\Programs\Python\Python311\python.exe' -m autosub_zh.ui_server
