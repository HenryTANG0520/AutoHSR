# 日常桌面视图接线

组件基于 `c8e3777` 和 P1 指南。桌面外壳继续管理页面、底栏、运行锁、F9／F10 和运行记录。[界面与交互指南](ui-ux-guide.md)

| 调用 | 共享路由接点 |
| --- | --- |
| `DailyPanel(parent, ui, start=start)` | 放在指南内容区。从「每日实训 → 持续委托」进入时调用 `panel.show(ASSIGNMENTS)`，从「生存索引 → 培养目标」进入时调用 `panel.show(PREVIEW)`。返回恢复原卡片或入口焦点。 |
| `panel.primary_label`、`panel.invoke_primary()` | 绑定共享底栏的文字及命令。保持「开始计划」只在原日常页面上使用。 |
| `start(operation, *, build_target_selection=None)` | `ASSIGNMENTS` 用 `assignment_runner(settings, emit, root=...)` 创建正式单任务 `TaskWorkflowRunner`。`PREVIEW`、`DRAFT` 用原生 `Runner`，仅草稿传入 `BuildTargetSelection`。以操作范围冻结草稿设置，结果留在各自面板。 |
| `panel.set_busy(busy)`、`panel.present(operation, report)` | 转发运行锁和本次终态报告。`operation` 用桌面发起的路由键，委托后端报告自身为 `task_workflow`。重建视图时重新投影当前页和最新报告。 |
| `support_result_text(report)` | 普通日常报告可在本次运行详情中显示支援需求、入队和待核对反馈。体力计划结果已使用同一函数。 |

培养页从当前游戏画面读取材料，用户选定来源和次数后才生成草稿。点击「加入体力计划」会重新核对本次发布文件及哈希，再通过原编辑器写入草稿列表。只有后续明确保存设置才写入配置。生存索引挑战设置与体力计划表均可打开已有支援偏好弹窗。

离线核对覆盖 100%、150%、200% 下的最小窗口、单委托子报告与改写对照、培养材料零持有、生成参数、草稿文件改写、显式加入、配置不变及支援结果。单委托、培养预览、日常支援和体力计划共 94 项定向单测通过，体力计划另通过 144 项布局检查。共享路由与打包版待中央整合验收。[假后端桌面检查](../tools/daily_panel_smoke.py)
