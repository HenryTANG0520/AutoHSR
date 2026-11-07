# 助手更新与回滚

使用 AutoHSR 的 CLI 检查最新正式版，或下载 Windows x64 便携包到明确指定的新文件。

```powershell
python -m autohsr --app-update-check
python -m autohsr --app-update-stage 'D:\Downloads\AutoHSR-update.zip'
```

检查通过 GitHub 的正式版入口核对版本标签和同一发布的 SHA-256 文件。返回 `available`、`current` 或 `local_ahead`。检查不下载 ZIP；可显式暂存同版本用于重新取得便携包。发布版本早于当前版本时拒绝暂存。[AutoHSR 正式发布](https://github.com/HenryTANG0520/AutoHSR/releases/latest) · [GitHub 正式版链接约定](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases)

暂存目标的父目录须已存在，并支持硬链接。程序在同目录下载到临时文件，核对完整 SHA-256 和便携包基本布局，再排他发布 ZIP。最多下载 512 MiB。失败或停止时清理本次临时文件，保留已有同名文件。回执记录正式版本和包哈希，暂存不改动已有助手、配置、`runs` 或通知凭据。

关闭目标便携版，从源码或另一份助手运行安装命令。在线安装重新核对 GitHub 的最新正式版与 ZIP 哈希。离线安装可明确指定此前从同一正式发布取得的 `.sha256` 文件，程序按其记录校验 ZIP。

```powershell
python -m autohsr --app-update-install 'D:\Downloads\AutoHSR-update.zip' --app-update-target 'D:\Apps\AutoHSR'
python -m autohsr --app-update-install 'D:\Downloads\AutoHSR-update.zip' --app-update-target 'D:\Apps\AutoHSR' --app-update-checksum 'D:\Downloads\AutoHSR-v0.2.0-windows-x64.zip.sha256'
python -m autohsr --app-update-status 'D:\Apps\AutoHSR'
```

安装只替换 `AutoHSR.exe` 和 `_internal`。配置、运行记录、通知凭据、定时方案及其他文件留在原位。安装期间会先移出旧 EXE，最后再发布新 EXE。更新失败会尝试恢复旧运行文件。断电或强制终止后，状态命令按原文件标识和实际位置判断是否中断。

手动启动新版核对，退出后选择验收或回滚。回滚也可恢复已中断的安装。验收会清理仍保留的更新副本，并允许下一次安装。若清理遇到占用，回执中的 `cleanup_pending` 指出仍待清理的目录名。状态和回滚无需联网。

```powershell
python -m autohsr --app-update-rollback 'D:\Apps\AutoHSR'
python -m autohsr --app-update-accept 'D:\Apps\AutoHSR'
```

## 独立更新器交接

```powershell
python -m autohsr --app-update-handoff 'D:\Apps\AutoHSR'
```

带版本标记的便携包支持自动交接。命令核对正式发布版本，只有正式版更高才发起更新。打包版使用独立更新器的副本，源码入口使用独立 Python 进程。旧发布包若没有版本标记，可先使用上面的手动安装入口。

更新器下载并校验 ZIP 后，最多等目标助手自行退出 120 秒。它替换运行文件，再从新安装启动探针，核对版本并加载 GUI 模块和 Tcl 运行时。探针失败会恢复旧运行文件，确认通过后默认尝试启动桌面。可用 `--app-update-no-restart` 保留探针检查并跳过桌面启动。

交接命令返回本次任务编号。进度证据保存在安装目录的 `runs/app-update/<编号>/`。结束后查看 `result.json`，其中 `runtime_verified` 表示启动探针通过，`desktop_restart: ready` 表示已收到本次新版的界面就绪信号。普通启动在主窗口映射后报告，管理员模式沿用现有启动通道的就绪信号。进程提前退出、回执不符或 40 秒内未就绪时，结果为部分完成并保留旧运行文件。核对后可退出新版，再执行验收或回滚。打包版的任务目录可在更新器退出后清理其临时副本。

三月七同样在确认新版后交给独立更新器。AutoHSR 目前通过 CLI 发起交接，桌面操作入口待接入。[三月七固定更新入口](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/version/app_update.py)
