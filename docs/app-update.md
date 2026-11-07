# 助手更新检查与暂存

使用 AutoHSR 的 CLI 检查最新正式版，或下载 Windows x64 便携包到明确指定的新文件。

```powershell
python -m autohsr --app-update-check
python -m autohsr --app-update-stage 'D:\Downloads\AutoHSR-update.zip'
```

检查通过 GitHub 的正式版入口核对版本标签和同一发布的 SHA-256 文件。返回 `available`、`current` 或 `local_ahead`。检查不下载 ZIP；可显式暂存同版本用于重新取得便携包。发布版本早于当前版本时拒绝暂存。[AutoHSR 正式发布](https://github.com/HenryTANG0520/AutoHSR/releases/latest) · [GitHub 正式版链接约定](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases)

暂存目标的父目录须已存在，并支持硬链接。程序在同目录下载到临时文件，核对完整 SHA-256 和便携包基本布局，再排他发布 ZIP。最多下载 512 MiB。失败或停止时清理本次临时文件，保留已有同名文件。回执记录正式版本和包哈希，暂存不改动已有助手、配置、`runs` 或通知凭据。

三月七在发现新版后将下载和更新交给独立更新器。AutoHSR 已接通发布识别与包暂存，后续还需独立更新进程在助手退出后替换运行文件、保留数据并核验重启与回滚。[三月七固定更新入口](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/version/app_update.py)
