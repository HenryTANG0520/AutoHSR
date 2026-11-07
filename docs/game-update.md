# 游戏更新与预下载核对

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

成功读取返回 0，读取待核实返回 1，用法错误返回 2，主动停止返回 130。JSON 中只含版本、渠道及分类，不含路径、账户或资源包链接。此工具查询的是包清单，下载进度、预下载是否已缓存和安装完成由启动器执行路径另外核对。

三月七把游戏更新与预下载分为两个入口，按启动器类型选择游戏，再分别处理更新按钮与预下载确认。AutoHSR 先接通本机和清单核对。启动器点击、下载进度与安装后复核仍待接入和实机验证。[三月七固定源码](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/game/__init__.py#L311-L435) · [三月七国际服适配](https://github.com/moesnow/March7thAssistant/pull/1253)
