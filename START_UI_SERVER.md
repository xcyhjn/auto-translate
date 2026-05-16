# 启动本地平台

如果网页按钮或翻译阶段出现不稳定，请不要直接依赖后台静默服务，改用这个脚本启动：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\autosub_zh\start_ui_server.ps1"
```

这个脚本会：

1. 进入正确的项目目录
2. 自动把 CUDA 12.8 的 `bin` 加入当前进程 PATH
3. 自动把 `HTTP_PROXY` / `HTTPS_PROXY` 指向 `http://127.0.0.1:7890`
4. 在当前窗口前台启动 `autosub_zh.ui_server`

然后在浏览器里打开：

```text
http://127.0.0.1:8777
```

只要这个 PowerShell 窗口还开着，平台服务就会一直在线。
