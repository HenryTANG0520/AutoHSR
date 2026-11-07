"""Withdrawn Tk panel, fake shared tool host, and synthetic record files."""
from concurrent.futures import ThreadPoolExecutor
import gc
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
from threading import Event
import tkinter as tk
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autohsr import theme
from autohsr.desktop_warp import ALL_ACCOUNTS, GAME_CACHE, LINK_FILE, PAGE_SIZE, build_warp_panel
from autohsr.warp_records import export, parse


def run_file_job(work, cancel):
    # A busy worker can trigger cyclic collection during normal allocation.
    gc.collect()
    return work(cancel)


class ToolHost:
    def __init__(self, root):
        self.root = root
        self.ui_scale = 1
        self.busy = self.closing = False
        self.stop_requested = Event()
        self.accepts = True
        self.pending = None
        self.started = []

    def _submit_tool_job(self, title, work, on_done, on_error):
        if self.busy or self.closing or not self.accepts:
            return False
        self.started.append(title)
        self.busy = True
        self.stop_requested.clear()
        self.pending = work, on_done, on_error
        return True

    def _tool_action_changed(self):
        self.warp_panel.refresh_actions()

    def complete(self, before_delivery=None):
        work, on_done, on_error = self.pending
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_file_job, work, self.stop_requested)
            try:
                value = future.result(timeout=12)
            except Exception as error:
                callback, value = on_error, error
            else:
                callback = on_done
        if before_delivery is not None:
            before_delivery()
        self.pending = None
        self.busy = False
        callback(value)


def record(index):
    return dict(id=str(9007199254740993000 + index), gacha_id="1001", gacha_type="11", item_id="1000",
                time="2026-11-01 08:00:00", name=f"虚构物品 {index}", item_type="角色", rank_type="5", count="1")


LINK = ("https://webstatic.mihoyo.com/?game_biz=hkrpg_cn&lang=zh-cn"
        "&auth_appid=webview_gacha&authkey=synthetic-private-token")


class WarpPanelSmoke(unittest.TestCase):
    def setUp(self):
        root = tk.Tk()
        root.withdraw()
        root.geometry("1100x800")
        self.host = ToolHost(root)
        self.panel = None
        self.addCleanup(self.destroy_host)
        theme.apply_theme(root, 1)
        self.replace_panel()
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.source = self.folder / "synthetic.json"
        accounts = [dict(uid="100000000", timezone=8, lang="zh-cn",
                         list=[record(index) for index in range(1, PAGE_SIZE + 6)]),
                    dict(uid="200000000", timezone=8, lang="zh-cn", list=[])]
        self.original = json.dumps(export(accounts)).encode("utf8")
        self.source.write_bytes(self.original)

    def destroy_host(self):
        host = self.host
        root = host.root
        host.pending = host.warp_panel = host.root = None
        self.panel = self.host = None
        root.destroy()
        del host, root
        # Release dead Tk interpreters on their creating thread between tests.
        gc.collect()

    def replace_panel(self):
        old = getattr(self.host, "warp_panel", None)
        if old is not None:
            old.destroy()
        panel = build_warp_panel(self.host.root, self.host)
        panel.pack(fill="both", expand=True)
        self.host.warp_panel = self.panel = panel
        panel.refresh_actions()
        self.host.root.update_idletasks()

    def start_import(self):
        with patch("autohsr.desktop_warp.filedialog.askopenfilenames", return_value=(str(self.source),)):
            self.panel.import_files()

    def load_source(self):
        self.start_import()
        self.host.complete()
        self.assertEqual(self.panel.last_result["status"], "success")

    def choose_account(self, label):
        self.panel.account.set(label)
        self.panel._choose_account()

    def choose_format(self, label):
        self.panel.format.set(label)
        self.panel._choose_format()

    def choose_reader(self, label):
        self.panel.reader.set(label)
        self.panel._choose_reader()
        return self.panel.primary_action()[1]

    def choose_pool(self, key):
        self.panel.overview.selection_set(key)
        self.panel._choose_pool()

    def save_to(self, path):
        with patch("autohsr.desktop_warp.filedialog.asksaveasfilename", return_value=str(path)) as dialog:
            self.panel.export()
        self.assertIs(dialog.call_args.kwargs["confirmoverwrite"], False)
        self.host.complete()

    def test_import_owns_one_shared_job_and_keeps_account_selection_explicit(self):
        self.assertTrue(self.panel.can_import)
        self.assertFalse(self.panel.can_export)
        self.start_import()
        self.assertTrue(self.host.busy)
        self.assertTrue(self.panel.account.instate(("disabled",)))
        with patch("autohsr.desktop_warp.filedialog.askopenfilenames") as dialog:
            self.panel.import_files()
            dialog.assert_not_called()
        self.host.complete()
        self.assertEqual(self.host.started, ["分析跃迁记录"])
        self.assertEqual(tuple(self.panel.account.cget("values")),
                         (ALL_ACCOUNTS, "UID 100000000", "UID 200000000"))
        self.assertEqual(self.panel.account.current(), -1)
        self.assertFalse(self.panel.can_export)
        self.assertEqual(self.panel.overview.get_children(), ())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_local_legacy_merge_requires_explicit_account_and_exports_only_that_account(self):
        from autohsr.tests.test_warp_records import compact_legacy_uigf, group

        legacy = self.folder / 'old.json'
        current = self.folder / 'current.json'
        other = self.folder / 'other.json'
        legacy.write_text(json.dumps(compact_legacy_uigf()), encoding='utf8')
        current.write_text(json.dumps(export([group()], format='srgf')), encoding='utf8')
        other.write_text(json.dumps(export([dict(group(), uid='200000000')])), encoding='utf8')
        originals = {path: path.read_bytes() for path in (legacy, current, other)}
        with patch('autohsr.desktop_warp.filedialog.askopenfilenames',
                   return_value=tuple(map(str, originals))):
            self.panel.import_files()
        self.host.complete()
        self.assertEqual(self.panel.last_result['status'], 'success')
        self.assertFalse(self.panel.can_export)
        self.choose_account('UID 100000000')
        self.choose_format('SRGF JSON')
        destination = self.folder / 'selected.json'
        self.save_to(destination)
        accounts, details = parse(json.loads(destination.read_text(encoding='utf8')))
        self.assertEqual(details['format'], 'srgf-v1.0')
        combined, = accounts
        self.assertEqual((combined['uid'], combined['lang']), ('100000000', 'zh-cn'))
        self.assertEqual([row['id'] for row in combined['list']], ['9007199254740993001', '9007199254740993002'])
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_summary_and_paginated_five_star_details_follow_explicit_selection(self):
        self.load_source()
        self.choose_account("UID 200000000")
        self.assertEqual(len(self.panel.overview.get_children()), 6)
        self.assertEqual(self.panel.overview.heading("3", "text"), "三星")
        self.assertEqual(str(self.panel.overview.item("11", "values")[1]), "0")
        self.choose_pool("11")
        self.assertFalse(self.panel.history.get_children())
        self.choose_account("UID 100000000")
        self.choose_pool("11")
        self.assertEqual(len(self.panel.history.get_children()), PAGE_SIZE)
        self.assertEqual(self.panel.history.get_children()[0], str(PAGE_SIZE + 5))
        self.assertIn(f"角色 {PAGE_SIZE + 5}", self.panel.detail_caption.cget("text"))
        self.panel.next_page.invoke()
        self.assertEqual(len(self.panel.history.get_children()), 5)
        first = self.panel.history.item("1", "values")
        self.assertEqual(first[5], "窗口前缀")
        self.assertEqual(str(first[-1]), str(9007199254740993001))
        self.assertTrue(self.panel.next_page.instate(("disabled",)))
        self.assertLess(self.panel.winfo_reqwidth(), 1050)
        self.assertLess(self.panel.winfo_reqheight(), 580)

    def test_existing_formats_and_scope_use_original_backend(self):
        self.load_source()
        self.choose_account(ALL_ACCOUNTS)
        self.choose_format("SRGF JSON")
        self.assertFalse(self.panel.can_export)
        self.choose_format("UIGF JSON")
        both = self.folder / "both.json"
        self.save_to(both)
        self.assertEqual(self.panel.last_result["format"], "uigf-v4.2")
        accounts, _ = parse(json.loads(both.read_text("utf8")))
        self.assertEqual(len(accounts), 2)
        self.choose_account("UID 200000000")
        self.choose_format("SRGF JSON")
        one = self.folder / "selected.srgf.json"
        self.save_to(one)
        accounts, _ = parse(json.loads(one.read_text("utf8")))
        self.assertEqual([row["uid"] for row in accounts], ["200000000"])
        self.choose_format("Excel XLSX")
        workbook = self.folder / "selected.xlsx"
        self.save_to(workbook)
        self.assertEqual(self.panel.last_result["output"], str(workbook))
        self.assertEqual(workbook.read_bytes()[:2], b"PK")
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_existing_output_and_changed_source_preserve_prior_view_and_files(self):
        self.load_source()
        self.choose_account("UID 100000000")
        existing = self.folder / "keep.json"
        existing.write_bytes(b"keep exactly")
        self.save_to(existing)
        self.assertEqual(self.panel.last_result["status"], "failed")
        self.assertEqual(existing.read_bytes(), b"keep exactly")
        self.source.write_bytes(self.original + b"\n")
        target = self.folder / "new.json"
        with patch("autohsr.desktop_warp.warp_service.run") as backend:
            self.save_to(target)
            backend.assert_not_called()
        self.assertIn("原件内容已改变", self.panel.feedback.cget("text"))
        self.assertFalse(target.exists())
        self.assertEqual(self.panel.account.get(), "UID 100000000")
        self.assertEqual(self.source.read_bytes(), self.original + b"\n")

    def test_export_receipt_requires_a_file_and_does_not_display_private_errors(self):
        self.load_source()
        self.choose_account("UID 100000000")
        path = self.folder / "never-published.json"
        claimed = dict(status="success", mode="export", format="uigf-v4.2", output_sha256="0" * 64)
        with patch("autohsr.desktop_warp.warp_service.run", return_value=claimed):
            self.save_to(path)
        self.assertEqual(self.panel.last_result["status"], "failed")
        self.assertIn("回执待核对", self.panel.feedback.cget("text"))
        with patch("autohsr.desktop_warp.warp_service.run", side_effect=OSError("synthetic private path")):
            self.save_to(path)
        self.assertEqual(self.panel.last_result["status"], "failed")
        self.assertNotIn("synthetic private path", self.panel.feedback.cget("text"))
        self.assertFalse(path.exists())

        def mismatched_receipt(**_options):
            path.write_bytes(b"other bytes")
            return claimed

        with patch("autohsr.desktop_warp.warp_service.run", side_effect=mismatched_receipt):
            self.save_to(path)
        self.assertEqual(self.panel.last_result["status"], "failed")
        self.assertIn("回执待核对", self.panel.feedback.cget("text"))
        self.assertEqual(path.read_bytes(), b"other bytes")

    def test_pending_result_and_selection_survive_rebuild_and_cancel(self):
        self.start_import()
        self.replace_panel()
        self.assertFalse(self.panel.can_import)
        self.host.complete()
        self.assertEqual(self.panel.last_result["status"], "success")
        self.choose_account("UID 100000000")
        self.choose_pool("11")
        self.choose_format("Excel XLSX")
        self.replace_panel()
        self.assertEqual(self.panel.account.get(), "UID 100000000")
        self.assertEqual(self.panel.overview.selection(), ("11",))
        self.assertEqual(self.panel.format.get(), "Excel XLSX")
        self.start_import()
        self.panel.cancel()
        self.host.complete()
        self.assertEqual(self.panel.last_result["status"], "stopped")
        self.assertEqual(self.panel.account.get(), "UID 100000000")
        self.assertTrue(self.panel.can_import)

    def test_file_dialog_cancel_or_host_refusal_leaves_previous_result(self):
        self.load_source()
        prior = self.panel.last_result
        with patch("autohsr.desktop_warp.filedialog.askopenfilenames", return_value=()):
            self.panel.import_files()
        self.assertEqual(self.host.started, ["分析跃迁记录"])
        self.host.accepts = False
        self.start_import()
        self.assertIsNone(self.host.pending)
        self.assertTrue(self.panel.can_import)
        self.assertEqual(self.panel.last_result, prior)

    def test_link_fetch_exports_the_displayed_snapshot_after_rebuild_without_refetch(self):
        link = self.folder / "private-link.txt"
        link.write_text(LINK, encoding="utf8")
        calls = []

        def request(url):
            query = parse_qs(urlsplit(url).query)
            calls.append((query['gacha_type'][0], query['page'][0]))
            rows = [dict(record(1), uid='100000000', lang='zh-cn')] if calls[-1] == ('11', '1') else []
            return dict(retcode=0, data=dict(list=rows, region_time_zone=8))

        with (patch('autohsr.warp_fetch.request_page', side_effect=request),
              patch('autohsr.warp_fetch.time.sleep'),
              patch('autohsr.desktop_warp.filedialog.askopenfilename', return_value=str(link))):
            action = self.choose_reader(LINK_FILE)
            self.assertEqual(self.panel.primary_action()[0], '联网读取链接文件')
            self.assertEqual(calls, [])
            action()
            self.replace_panel()
            self.assertTrue(self.panel.reader.instate(('disabled',)))
            self.host.complete()
            self.assertEqual(self.panel.last_result['status'], 'success')
            self.assertIn(LINK_FILE, self.panel.sources_label.cget('text'))
            self.assertFalse(self.panel.can_export)
            self.assertTrue(self.panel.can_merge)
            self.assertEqual(link.read_text('utf8'), LINK)
            link.unlink()  # Export is based on the completed fetch, not on a fresh link read.
            self.choose_account('UID 100000000')
            target = self.folder / 'fetched.json'
            self.save_to(target)
            with patch('autohsr.desktop_warp.filedialog.askopenfilenames', return_value=()):
                self.panel.merge_button.invoke()
            self.assertIsNone(self.host.pending)
            with patch('autohsr.desktop_warp.filedialog.askopenfilenames', return_value=(str(self.source),)):
                self.panel.merge_button.invoke()
                self.replace_panel()
                self.assertFalse(self.panel.can_merge)
                self.host.complete(before_delivery=self.panel.cancel)
            self.assertEqual(self.panel.last_result['status'], 'stopped')
            self.assertEqual(self.panel.account.get(), 'UID 100000000')
            self.assertNotIn('本地文件', self.panel.sources_label.cget('text'))
            with patch('autohsr.desktop_warp.filedialog.askopenfilenames', return_value=(str(self.source),)):
                self.panel.merge_button.invoke()
                self.assertTrue(self.panel.merge_button.instate(('disabled',)))
                self.host.complete()
            self.assertIn('1 份本地文件', self.panel.sources_label.cget('text'))
            self.assertEqual(self.panel.last_result['status'], 'success')
            self.assertFalse(self.panel.can_export)
            self.choose_account(ALL_ACCOUNTS)
            merged_path = self.folder / 'merged.json'
            self.save_to(merged_path)
            self.assertEqual(self.panel.last_result['status'], 'success')
            conflict = self.folder / 'conflict.json'
            bad_record = dict(record(1), name='冲突样本')
            conflict.write_text(json.dumps(export([dict(uid='100000000', timezone=8, lang='zh-cn', list=[bad_record])])),
                                encoding='utf8')
            with patch('autohsr.desktop_warp.filedialog.askopenfilenames', return_value=(str(conflict),)):
                self.panel.merge_button.invoke()
                self.host.complete()
            self.assertEqual(self.panel.last_result['status'], 'failed')
            self.assertIn('冲突', self.panel.feedback.cget('text'))
            self.assertIn('1 份本地文件', self.panel.sources_label.cget('text'))
            self.assertEqual(self.panel.account.get(), ALL_ACCOUNTS)
            self.assertTrue(self.panel.can_export)
        self.assertEqual(len(calls), 7)
        self.assertEqual(self.source.read_bytes(), self.original)
        raw = target.read_text('utf8')
        self.assertNotIn('synthetic-private-token', raw)
        accounts, _ = parse(json.loads(raw))
        self.assertEqual([row['id'] for row in accounts[0]['list']], [record(1)['id']])
        merged_raw = merged_path.read_text('utf8')
        self.assertNotIn('synthetic-private-token', merged_raw)
        merged, _ = parse(json.loads(merged_raw))
        self.assertEqual([(row['uid'], len(row['list'])) for row in merged],
                         [('100000000', PAGE_SIZE + 5), ('200000000', 0)])

    def test_cache_cancel_and_failed_online_read_leave_prior_local_result_available(self):
        self.load_source()
        self.choose_account('UID 100000000')
        action = self.choose_reader(GAME_CACHE)
        cache = self.folder / 'StarRail_Data' / 'webCaches' / '1' / 'Cache' / 'Cache_Data' / 'data_2'
        cache.parent.mkdir(parents=True)
        cache.write_text(LINK, encoding='utf8')
        with patch('autohsr.warp_fetch.request_page', return_value={'retcode': -101}) as request:
            with patch('autohsr.desktop_warp.filedialog.askdirectory', return_value=''):
                action()
            self.assertIsNone(self.host.pending)
            request.assert_not_called()
            with patch('autohsr.desktop_warp.filedialog.askdirectory', return_value=str(cache.parents[4])):
                action()
            self.host.complete()
            request.assert_called_once()
        self.assertEqual(self.panel.last_result['status'], 'failed')
        self.assertIn('鉴权已过期', self.panel.feedback.cget('text'))
        self.assertNotIn('synthetic-private-token', self.panel.feedback.cget('text'))
        self.assertIn('1 份文件', self.panel.sources_label.cget('text'))
        self.assertEqual(self.panel.account.get(), 'UID 100000000')
        self.assertTrue(self.panel.can_export)
        self.assertEqual(cache.read_text('utf8'), LINK)


if __name__ == "__main__":
    unittest.main()
