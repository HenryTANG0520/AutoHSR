# 游戏更新与预下载核对

在「设置 → 工具 → 游戏更新」选择国服或国际服，再选择更新或预下载。检查后会分别显示本机版本、官方发布和预下载版本。有对应的包时，可以从同一页打开官方启动器继续。

打开前会重新读取官方版本，核对星铁安装与该渠道的注册表记录、启动器文件和 Windows 签名，并确认助手没有原生任务或任务流持有执行权。启动请求交给该渠道的米哈游启动器或 HoYoPlay。

打开后可在官方启动器手动下载，也可回到工具页点「确认启动下载」，再把对应渠道的星铁启动器页面置于前台。助手会重新核对目标版本、安装、Windows 签名和前台窗口。连续两帧核实星铁页面和同一个按钮后，更新只提交一次「更新游戏」。预下载先打开「预下载」，识别到专用弹窗后才提交一次「确认下载」。可以用 F10 停止尚未提交的操作。

启动器出现对应的下载或安装状态时，工具会显示核实反馈。若按钮或后续页面待核对，可在启动器内查看和处理。游戏更新交接后，助手还会在后台读取同一安装的版本，连续两次读到同一个达到目标的版本时显示核实通过。版本暂时无法读取会继续等待，安装来源改变或达到两小时跟踪时限时停止。可主动停止跟踪或点击「核对安装版本」立即检查。

有完整游戏包尺寸数据时，助手会显示差分包或完整包的合计。差分包按当前安装版本匹配，语音包和解压空间由启动器计算。预下载的实际进度和缓存完成状态由启动器显示。

### 手动启动时交接官方启动器

「设置 → 游戏连接 → 进入游戏」的普通手动启动和 CLI `--launch` 先尝试直接启动或复用现有游戏窗口。若 Windows 要求提升权限，助手核对所选星铁安装、注册表渠道及官方启动器签名，再请求打开对应星铁页面。提示「已请求官方启动器显示星铁页面」后，请在启动器点击「开始游戏」。

该交接只读取本地安装信息。来源或签名无法核实时保留权限错误与交接原因。自动日常和已启用的方案账号自动进入继续沿用原权限及账号核验。

## CLI 只读核对

先选择官方包清单对应的渠道，再指定该渠道的星铁安装位置。默认沿用本次 AutoHSR 配置中的游戏路径，`--game-path` 可覆盖本次位置。

```powershell
python -m autohsr --game-update-check cn
python -m autohsr --game-update-check global --game-path 'X:\Star Rail\Games\StarRail.exe'
```

`cn` 对应国服米哈游启动器的 `hkrpg_cn`，`global` 对应国际服 HoYoPlay 的 `hkrpg_global`。包清单使用固定官方 HTTPS 地址，回执中的渠道表示本次选择的远端清单。请选同渠道的本机安装。程序只从所选安装下的 `config.ini` 读取 `game_version`，并在网络读取后再次核对安装来源。[国服官方包清单](https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages?launcher_id=jGHBHlcOq1&game_ids%5B%5D=64kMb5iAWu) · [国际服官方包清单](https://sg-hyp-api.hoyoverse.com/hyp/hyp-connect/api/getGamePackages?launcher_id=VYTpXlbWo8&game_ids%5B%5D=4ziysqXOQ8)

| 回执 | 含义 |
| --- | --- |
| `update: available` | 所选清单的发布版本高于本机版本 |
| `update: current` | 两个版本一致 |
| `update: local_ahead` | 本机版本高于本次读取的清单 |
| `pre_download: advertised` | 清单列有比本机版本更新的预下载包 |
| `pre_download: not_advertised` | 本次清单未列预下载包 |
| `pre_download: local_at_or_ahead` | 本机版本已达或超过清单所列预下载版本 |
| `unknown` | 安装来源、包清单或网络反馈待核实 |

成功读取返回 0，读取待核实返回 1，用法错误返回 2，主动停止返回 130。JSON 输出版本、渠道、分类及可核对的包体积。此工具查询的是包清单，下载进度、预下载是否已缓存和安装完成由启动器执行路径另外核对。

清单尺寸完整时，JSON 另含 `update_package` 或 `pre_download_package`，给出包类型、文件数及合计字节数。

三月七分开处理更新与预下载，并通过启动器参数选择星铁渠道。AutoHSR 沿用这两个入口和按钮顺序，增加安装绑定、逐步双帧核验及版本跟踪。下载按钮和反馈已用合成画面验收，真实启动器布局、下载百分比和预下载完成仍待核对。[三月七固定源码](https://github.com/moesnow/March7thAssistant/blob/v2026.11.7/tasks/game/__init__.py#L350-L490) · [三月七国际服适配](https://github.com/moesnow/March7thAssistant/pull/1253)
