"""The guide's warp-record view, backed by the existing record service."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import re
from tkinter import filedialog, ttk

from . import theme, warp_service
from .storage import hold_read_sources
from .warp_fetch import WarpStopped, checkpoint
from .warp_records import MAX_BYTES, POOLS, WarpError
from .warp_statistics import POOL_NAMES

ALL_ACCOUNTS = "全部账号"
LOCAL_RECORDS, GAME_CACHE, LINK_FILE = "本地记录", "游戏缓存", "链接文件"
RECORD_SOURCES = (LOCAL_RECORDS, GAME_CACHE, LINK_FILE)
FORMATS = {
    "UIGF JSON": ("uigf", ".json", "uigf-v4.2"),
    "SRGF JSON": ("srgf", ".srgf.json", "srgf-v1.0"),
    "Excel XLSX": ("xlsx", ".xlsx", "xlsx"),
}
SCOPE_LABELS = {"window_prefix": "窗口前缀", "unknown_rank": "星级缺失", "observed": "可用区间"}
PAGE_SIZE = 50


@dataclass
class _State:
    sources: tuple[Path, ...] = ()
    digests: tuple[str, ...] = ()
    snapshot: warp_service.WarpSnapshot | None = field(default=None, repr=False)
    snapshot_source: str = ""
    reader: str = LOCAL_RECORDS
    accounts: tuple[dict, ...] = ()
    choice: str = ""
    pool: str = ""
    format: str = "UIGF JSON"
    page: int = 0
    message: str = "选择记录来源后从底栏读取。联网来源使用官方跃迁记录接口。"
    result: dict = field(default_factory=dict)
    job: object | None = None
    revision: int = 0


def _digests(paths, cancel):
    hashes = []
    for path in paths:
        digest = sha256()
        size = 0
        checkpoint(cancel)
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                checkpoint(cancel)
                size += len(block)
                if size > MAX_BYTES:
                    raise WarpError("记录文件超过32 MiB上限。")
                digest.update(block)
        hashes.append(digest.hexdigest())
    return tuple(hashes)


def _display(value):
    if value is None:
        return "—"
    return " ".join(str(value).split()).replace("\x00", "�") or "—"


def _replace_rows(tree, rows):
    previous = tree.get_children()
    if previous:
        tree.delete(*previous)
    for key, values in rows:
        tree.insert("", "end", iid=key, values=values)


class WarpPanel(ttk.Frame):
    def __init__(self, parent, ui, state):
        self.ui, self.model = ui, state
        scale = ui.ui_scale
        self.px = lambda size: round(size * scale)
        super().__init__(parent, style="Panel.TFrame", padding=self.px(12))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(6, weight=1)
        self._rendered = -1

        heading = ttk.Frame(self, style="Panel.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        ttk.Label(heading, text="跃迁记录", style="PageTitle.TLabel").pack(side="left")
        self.reader = ttk.Combobox(heading, values=RECORD_SOURCES, width=12, state="readonly")
        self.reader.pack(side="right")
        self.reader.bind("<<ComboboxSelected>>", self._choose_reader)
        ttk.Label(heading, text="读取来源", style="Hint.TLabel").pack(side="right", padx=(0, self.px(8)))
        self.sources_label = theme.wrapped_label(self, style="Hint.TLabel")
        self.sources_label.grid(row=1, column=0, sticky="ew", pady=(self.px(2), self.px(4)))
        controls = ttk.Frame(self, style="Panel.TFrame")
        controls.grid(row=2, column=0, sticky="ew")
        ttk.Label(controls, text="账号", style="Hint.TLabel").pack(side="left", padx=(0, self.px(8)))
        self.account = ttk.Combobox(controls, width=24, state="readonly")
        self.account.pack(side="left", padx=(0, self.px(16)))
        self.account.bind("<<ComboboxSelected>>", self._choose_account)
        ttk.Label(controls, text="格式", style="Hint.TLabel").pack(side="left", padx=(0, self.px(8)))
        self.format = ttk.Combobox(controls, values=tuple(FORMATS), width=12, state="readonly")
        self.format.pack(side="left", padx=(0, self.px(8)))
        self.format.bind("<<ComboboxSelected>>", self._choose_format)
        self.export_button = ttk.Button(controls, text="导出记录…", style="Panel.TButton", command=self.export)
        self.export_button.pack(side="left")

        self.feedback = theme.wrapped_label(self, style="Hint.TLabel")
        self.feedback.grid(row=3, column=0, sticky="ew", pady=(self.px(5), self.px(6)))
        self.overview = self._table(4, (
            ("pool", "卡池", 140), ("records", "记录", 58), ("3", "三星", 52), ("4", "四星", 52),
            ("5", "五星", 52), ("unknown", "未知星级", 74), ("tail", "观察尾段", 84),
            ("interval", "五星间隔均值", 108)), height=4, selectmode="browse")
        self.overview.bind("<<TreeviewSelect>>", self._choose_pool)
        self.detail_caption = theme.wrapped_label(self, style="Hint.TLabel")
        self.detail_caption.grid(row=5, column=0, sticky="ew", pady=(self.px(7), self.px(3)))
        self.history = self._table(6, (
            ("index", "本池序号", 76), ("name", "五星名称", 154), ("type", "类别", 76),
            ("span", "观察跨度", 78), ("interval", "已知间隔", 78), ("scope", "范围", 88),
            ("time", "原时间", 158), ("id", "记录 ID", 176)), height=3, selectmode="browse")
        pages = ttk.Frame(self, style="Panel.TFrame")
        pages.grid(row=7, column=0, sticky="ew", pady=(self.px(4), 0))
        self.page_caption = ttk.Label(pages, style="Hint.TLabel")
        self.page_caption.pack(side="left")
        self.next_page = ttk.Button(pages, text="下一页", style="Panel.TButton", command=lambda: self._turn_page(1))
        self.next_page.pack(side="right")
        self.prev_page = ttk.Button(pages, text="上一页", style="Panel.TButton", command=lambda: self._turn_page(-1))
        self.prev_page.pack(side="right", padx=(0, self.px(6)))
        self.refresh_actions()

    def _table(self, row, columns, *, height, selectmode):
        frame = ttk.Frame(self, style="Panel.TFrame")
        frame.grid(row=row, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=[key for key, _, _ in columns],
                            show="headings", height=height, selectmode=selectmode)
        for key, title, width in columns:
            tree.heading(key, text=title)
            anchor = "w" if key in ("pool", "name", "time", "id") else "center"
            tree.column(key, width=self.px(width), minwidth=self.px(width),
                        stretch=key in ("pool", "name"), anchor=anchor)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        return tree

    @property
    def can_import(self):
        return self._current() and self.model.job is None and not self.ui.busy and not self.ui.closing

    @property
    def can_export(self):
        model = self.model
        return (self.can_import and model.choice in self._choices()
                and (model.choice != ALL_ACCOUNTS or FORMATS[model.format][0] != "srgf"))

    @property
    def last_result(self):
        """Metadata for this tool's most recent result, kept in the local view."""
        return self.model.result.copy()

    def primary_action(self):
        label, action = {
            LOCAL_RECORDS: ("导入跃迁记录", self.import_files),
            GAME_CACHE: ("联网读取游戏缓存", self.fetch_cache),
            LINK_FILE: ("联网读取链接文件", self.fetch_link_file),
        }[self.model.reader]
        return label, action, self.can_import

    def focus_initial(self):
        target = self.account if self.model.accounts else self.reader
        if target is not None and not target.instate(("disabled",)):
            target.focus_set()

    def refresh_actions(self):
        model = self.model
        if self._rendered != model.revision:
            self._rendered = model.revision
            self._render()
        enabled = self.can_import and bool(model.accounts)
        self.reader.configure(state="readonly" if self.can_import else "disabled")
        self.account.configure(state="readonly" if enabled else "disabled")
        self.format.configure(state="readonly" if enabled else "disabled")
        self.export_button.configure(state="normal" if self.can_export else "disabled")
        last = max(0, (len(self._pool().get("five_star_history", ())) - 1) // PAGE_SIZE)
        self.prev_page.configure(state="normal" if model.page else "disabled")
        self.next_page.configure(state="normal" if model.page < last else "disabled")

    def _choices(self):
        accounts = self.model.accounts
        return {ALL_ACCOUNTS: None, **{f"UID {account['uid']}": account for account in accounts}} if accounts else {}

    def _account(self):
        return self._choices().get(self.model.choice) or {}

    def _pool(self):
        return self._account().get("pools", {}).get(self.model.pool, {})

    def _change(self):
        self.model.revision += 1
        self.refresh_actions()

    def _current(self):
        return getattr(self.ui, "warp_panel", self) is self

    def _choose_reader(self, _event=None):
        reader = self.reader.get()
        if self.can_import and reader in RECORD_SOURCES and reader != self.model.reader:
            self.model.reader = reader
            self._change()
            self.ui._tool_action_changed()

    def _choose_account(self, _event=None):
        choice = self.account.get()
        if self.can_import and choice in self._choices() and choice != self.model.choice:
            self.model.choice, self.model.pool, self.model.page = choice, "", 0
            self._change()

    def _choose_format(self, _event=None):
        choice = self.format.get()
        if self.can_import and choice in FORMATS and choice != self.model.format:
            self.model.format = choice
            self._change()

    def _choose_pool(self, _event=None):
        selected = self.overview.selection()
        if (self._current() and selected and selected[0] in self._account().get("pools", {})
                and selected[0] != self.model.pool):
            self.model.pool, self.model.page = selected[0], 0
            self._change()

    def _turn_page(self, direction):
        if not self._current():
            return
        last = max(0, (len(self._pool().get("five_star_history", ())) - 1) // PAGE_SIZE)
        page = max(0, min(last, self.model.page + direction))
        if page != self.model.page:
            self.model.page = page
            self._change()

    def _render(self):
        model = self.model
        self.account.configure(values=tuple(self._choices()))
        self.account.set(model.choice or "请选择账号")
        self.format.set(model.format)
        self.reader.set(model.reader)
        records = sum(sum(pool["records"] for pool in a["pools"].values()) for a in model.accounts)
        source = model.snapshot_source or (f"{len(model.sources)} 份文件" if model.sources else "")
        source_text = f"记录窗口 · {source} · {len(model.accounts)} 个账号 · {records} 条记录" if source else "尚未读取。"
        self.sources_label.configure(text=source_text)
        message = model.message
        if model.choice == ALL_ACCOUNTS and FORMATS[model.format][0] == "srgf":
            message += " SRGF 导出请选择一个账号。"
        self.feedback.configure(text=message)
        rows = []
        pools = self._account().get("pools", {})
        for key in POOLS:
            if key not in pools:
                continue
            pool = pools[key]
            ranks = pool["rank_counts"]
            mean = pool["mean_bounded_interval_records"]
            tail = str(pool["observed_tail_records"]) if pool["records"] else "—"
            if pool["records"] and pool["known_tail_records"] is None:
                tail += "（待核对）"
            rows.append((key, (POOL_NAMES[key], pool["records"], ranks["3"], ranks["4"], ranks["5"],
                               ranks["unknown"], tail, "—" if mean is None else f"{mean:.2f}")))
        _replace_rows(self.overview, rows)
        if model.pool in pools:
            self.overview.selection_set(model.pool)
            self.overview.see(model.pool)
        self._render_history()

    def _render_history(self):
        model = self.model
        pool = self._pool()
        history = pool.get("five_star_history", ())
        end = len(history) - model.page * PAGE_SIZE
        records = reversed(history[max(0, end - PAGE_SIZE):end])
        _replace_rows(self.history, (
            (str(entry["pool_index"]), (entry["pool_index"], _display(entry["name"]), _display(entry["item_type"]),
                                       entry["observed_span_records"], _display(entry["bounded_interval_records"]),
                                       SCOPE_LABELS.get(entry["scope"], "待核对"), entry["time"], entry["id"]))
            for entry in records))
        if pool:
            types = pool["item_type_counts"]
            shown = [f"{_display(entry['item_type'])[:24] if entry['item_type'] is not None else '类别未知'} {entry['records']}"
                     for entry in types[:4]]
            if len(types) > 4:
                shown.append(f"另有 {len(types) - 4} 类")
            category = " · ".join(shown) if shown else "暂无记录"
            caption = f"{POOL_NAMES[model.pool]} · 五星明细 · {category}"
        else:
            caption = "选择一个账号及卡池查看五星明细。"
        self.detail_caption.configure(text=caption)
        pages = (len(history) + PAGE_SIZE - 1) // PAGE_SIZE
        self.page_caption.configure(text=f"第 {model.page + 1}/{pages} 页 · 共 {len(history)} 条五星" if pages
                                   else ("所选卡池暂无五星记录" if pool else ""))

    def import_files(self):
        if not self.can_import:
            return
        selected = filedialog.askopenfilenames(parent=self.ui.root, title="选择本地跃迁记录",
                                               filetypes=[("UIGF / SRGF JSON", "*.json")])
        if selected and self.can_import:
            paths = selected if isinstance(selected, (list, tuple)) else self.tk.splitlist(selected)
            self._start("analysis", tuple(Path(path) for path in paths))

    def fetch_cache(self):
        if not self.can_import:
            return
        path = filedialog.askdirectory(parent=self.ui.root, title="选择 StarRail_Data 缓存目录", mustexist=True)
        if path and self.can_import:
            self._start("analysis", (), cache_dir=Path(path), snapshot_source=GAME_CACHE)

    def fetch_link_file(self):
        if not self.can_import:
            return
        path = filedialog.askopenfilename(parent=self.ui.root, title="选择 UTF-8 跃迁记录链接文件",
                                          filetypes=[("文字文件", "*.txt"), ("所有文件", "*")])
        if path and self.can_import:
            self._start("analysis", (), url_file=Path(path), snapshot_source=LINK_FILE)

    def export(self):
        if not self.can_export:
            return
        model = self.model
        frozen = model.revision
        kind, extension, result_format = FORMATS[model.format]
        target = filedialog.asksaveasfilename(parent=self.ui.root, title="另存跃迁记录",
            defaultextension=extension, initialfile=f"跃迁记录{extension}", confirmoverwrite=False,
            filetypes=[(model.format, "*.xlsx" if kind == "xlsx" else "*.json")])
        if target and self.can_export and frozen == model.revision:
            selected_uid = self._account().get("uid")
            self._start("export", model.sources, output=Path(target), kind=kind, selected_uid=selected_uid,
                        result_format=result_format)

    def cancel(self):
        if self.model.job is not None:
            self.ui.stop_requested.set()

    def _start(self, mode, paths, *, output=None, kind="uigf", selected_uid=None, result_format=None,
               url_file=None, cache_dir=None, snapshot_source=""):
        model, ui = self.model, self.ui
        expected = model.digests if output is not None else None
        existing_snapshot = model.snapshot if output is not None else None
        job, previous = object(), model.message

        def work(cancel_event):
            cancel = cancel_event.is_set
            checkpoint(cancel)
            snapshot, sources, digests = None, (), ()
            if snapshot_source:
                snapshot = warp_service.fetch_snapshot(url_file=url_file, cache_dir=cache_dir, cancel=cancel)
                result = snapshot.analyze(cancel=cancel)
            elif existing_snapshot is not None:
                result = existing_snapshot.export(output, format=kind, selected_uid=selected_uid, cancel=cancel)
            else:
                if len(paths) > 1000:
                    raise WarpError("最多一次导入1000份记录文件。")
                sources = tuple(path.resolve(strict=True) for path in paths)
                with hold_read_sources(sources):
                    digests = _digests(sources, cancel)
                    if expected is not None and digests != expected:
                        raise WarpError("导入原件内容已改变，请重新导入后再导出。")
                    if output is None:
                        result = warp_service.run(imports=sources, analysis_only=True, include_details=True, cancel=cancel)
                    else:
                        result = warp_service.run(imports=sources, output=output, format=kind,
                                                  selected_uid=selected_uid, cancel=cancel)
            if result.get("status") != "success" or result.get("mode") != mode:
                raise WarpError("本次跃迁结果待核对。")
            if output is None:
                detail = result.get("details") or {}
                accounts = detail.get("accounts")
                if (type(accounts) is not list or len(accounts) != result.get("accounts")
                        or any(type(account) is not dict or type(account.get("uid")) is not str
                               or type(account.get("pools")) is not dict for account in accounts)):
                    raise WarpError("本次账号与分池结果待核对。")
            elif (result.get("format") != result_format or not output.is_file()
                  or not re.fullmatch(r"[0-9a-f]{64}", result.get("output_sha256") or "")):
                raise WarpError("本次导出文件或回执待核对。")
            return result, sources, digests, snapshot

        def done(value):
            result, sources, digests, snapshot = value
            self._finish(job, result, sources, digests, output, snapshot=snapshot, snapshot_source=snapshot_source)

        def failed(error):
            stopped = isinstance(error, WarpStopped)
            message = ("本次操作已停止。" if stopped else str(error) if isinstance(error, WarpError)
                       else "读取或保存失败，请核对本地文件权限。")
            self._finish(job, dict(status="stopped" if stopped else "failed", mode=mode, message=message),
                         (), (), output)

        title = ("联网读取跃迁记录" if snapshot_source else
                 "分析跃迁记录" if output is None else "导出跃迁记录")
        model.job = job
        model.message = f"正在{title}…"
        self._change()
        try:
            accepted = ui._submit_tool_job(title, work, done, failed)
        except Exception as error:
            failed(error)
            return
        if not accepted and model.job is job:
            model.job, model.message = None, previous
            self._change()
        ui._tool_action_changed()

    def _finish(self, job, result, paths, digests, output, *, snapshot=None, snapshot_source=""):
        model, ui = self.model, self.ui
        if model.job is not job:
            return
        status = result["status"]
        model.result = {key: result[key] for key in ("status", "mode", "accounts", "records", "format",
                                                    "output_sha256", "message") if key in result}
        if status == "success" and output is None:
            model.sources, model.digests = paths, digests
            model.snapshot, model.snapshot_source = snapshot, snapshot_source
            model.accounts = tuple(result["details"]["accounts"])
            model.choice, model.pool, model.page = "", "", 0
            model.message = "分析完成。请选择账号。" if model.accounts else "分析完成。暂无账号记录。"
        elif status == "success":
            model.result["output"] = str(output)
            model.message = f"导出完成 · {output.name}"
        else:
            model.message = result["message"]
        model.job = None
        model.revision += 1
        panel = getattr(ui, "warp_panel", self)
        if panel is not None and panel.winfo_exists():
            panel.refresh_actions()
        ui._tool_action_changed()


def build_warp_panel(parent, ui):
    """Build a frame for the host to place and retain as `ui.warp_panel`.

    The host uses `primary_action` in the footer and calls `refresh_actions`
    after navigation or lock changes. Its tool job interface runs the file
    work and delivers the result on the Tk thread after releasing the lock.
    """
    if not hasattr(ui, "_warp_panel_state"):
        ui._warp_panel_state = _State()
    return WarpPanel(parent, ui, ui._warp_panel_state)
