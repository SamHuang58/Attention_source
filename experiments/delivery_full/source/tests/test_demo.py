"""Replay and demo must not hide changed observations or show a stale PASS."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def module(name, filename):
    spec=importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
runner=module('replay_runner', 'run_research.py')
demo=module('demo_entry', 'demo.py')


class DemoTests(unittest.TestCase):
    def test_replay_detects_changed_output_timing_and_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/'original',Path(d)/'replay'
            a.mkdir();b.mkdir()
            files=['rtl_results.csv','cycle_trace.csv','functional_coverage.json']
            for f in files:
                (a/f).write_text('same');(b/f).write_text('same')
            runner.verify_replay(a,b)
            for f in files:
                (b/f).write_text('changed')
                with self.assertRaisesRegex(RuntimeError,'reproducibility mismatch'):
                    runner.verify_replay(a,b)
                (b/f).write_text('same')
            (b/files[0]).unlink()
            with self.assertRaises(FileNotFoundError): runner.verify_replay(a,b)

    def test_failed_attempt_does_not_display_previous_demo(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            root=Path(d);(root/'experiments').mkdir()
            pointer=root/'experiments/latest_demo.json'
            pointer.write_text('{"run":"experiments/old_pass"}')
            def fail(*args,**kwargs):
                folder=root/'experiments/new_run';folder.mkdir()
                (folder/'manifest.json').write_text('{"status":"FAIL","error":"injected mismatch"}')
                return subprocess.CompletedProcess(args,1)
            with patch.object(demo,'ROOT',root), patch.object(sys,'argv',['demo','--name','new_run']), \
                 patch.object(demo.subprocess,'run',side_effect=fail), patch.object(demo,'view') as view:
                self.assertEqual(demo.main(),1)
                view.assert_not_called()
            self.assertEqual(json.loads(pointer.read_text())['run'],'experiments/new_run')
            self.assertIn('失败', (root/'experiments/new_run/summary.txt').read_text())

    def test_view_refuses_failed_run(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            (folder/'manifest.json').write_text('{"status":"FAIL"}')
            with self.assertRaisesRegex(ValueError,'未通过'): demo.view(folder)


if __name__=='__main__': unittest.main()
