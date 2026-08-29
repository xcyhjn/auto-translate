# 启动本地平台

如果网页按钮或翻译阶段出现不稳定，请不要直接依赖后台静默服务，改用这个脚本启动：

```powershell
powershell -ExecutionPolicy Bypass -File "D:\autosub_zh\scripts\start_ui_server.ps1"
```

这个脚本会：

1. 进入正确的项目目录
2. 把 `src/` 加入当前进程的 `PYTHONPATH`
3. 在存在 CUDA 12.8 时补充本地运行库路径
4. 按需读取 `AUTOSUB_PROXY_URL`，未设置时使用直连
5. 选择可用本地端口并在前台启动 `autosub_zh.ui_server`

然后打开终端显示的地址。默认地址是：

```text
http://127.0.0.1:8777
```

如果 `8777` 已被占用，脚本会尝试后续端口。只要这个 PowerShell 窗口还开着，平台服务就会一直在线。
