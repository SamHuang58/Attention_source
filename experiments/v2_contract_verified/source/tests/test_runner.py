"""Failure paths must preserve diagnostics and never publish an incomplete PASS."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('research_runner_under_test', ROOT / 'scripts/run_research.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def arguments(**updates):
    values = dict(name='test_run', timeout=10, seeds=[1], random=0, groups=0,
                  max_stall=0, netlist_stall=0, skip_netlist=True, skip_mutations=True)
    values.update(updates)
    return argparse.Namespace(**values)


class RunnerFailureTests(unittest.TestCase):
    def test_failed_run_retains_diagnostics_and_does_not_replace_latest_pass(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runner, 'ROOT', Path(folder)):
            latest = Path(folder) / 'experiments/latest.json'
            latest.parent.mkdir()
            latest.write_text('{"run":"previous_success"}', encoding='utf-8')
            before = latest.read_bytes()
            with patch.object(runner, 'parse_args', return_value=arguments()), \
                    patch.object(runner.Experiment, 'setup', side_effect=RuntimeError('deliberate setup failure')), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runner.main(), 1)
            manifest = json.loads((latest.parent / 'test_run/manifest.json').read_text())
            self.assertEqual(manifest['status'], 'FAIL')
            self.assertIn('deliberate setup failure', manifest['error'])
            self.assertIn('deliberate setup failure', (latest.parent / 'test_run/failure.txt').read_text())
            self.assertEqual(latest.read_bytes(), before)

    def test_run_directory_cannot_overwrite_previous_results(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runner, 'ROOT', Path(folder)):
            first = runner.Experiment(arguments())
            before = (first.folder / 'manifest.json').read_bytes()
            with self.assertRaises(FileExistsError):
                runner.Experiment(arguments())
            self.assertEqual((first.folder / 'manifest.json').read_bytes(), before)

    def test_command_failure_and_mutation_false_positive_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runner, 'ROOT', Path(folder)), \
                contextlib.redirect_stdout(io.StringIO()):
            experiment = runner.Experiment(arguments())
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                experiment.command([sys.executable, '-c', 'print("diagnostic");raise SystemExit(3)'], 'broken')
            self.assertIn('diagnostic', (experiment.logs / 'broken.log').read_text())
            with self.assertRaisesRegex(RuntimeError, 'escaped detection'):
                experiment.command([sys.executable, '-c', 'print("PASS")'], 'surviving_mutant', expected_failure=True)
            with self.assertRaisesRegex(RuntimeError, 'non-assertion'):
                experiment.command([sys.executable, '-c', 'raise SystemExit(1)'], 'tool_crash', expected_failure=True)

    def test_command_timeout_is_recorded(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runner, 'ROOT', Path(folder)), \
                contextlib.redirect_stdout(io.StringIO()):
            experiment = runner.Experiment(arguments(timeout=0.1))
            with self.assertRaisesRegex(RuntimeError, 'exceeded'):
                experiment.command([sys.executable, '-c', 'import time;time.sleep(3)'], 'hung')
            manifest = json.loads((experiment.folder / 'manifest.json').read_text())
            self.assertEqual(manifest['commands'][-1]['status'], 'TIMEOUT')

    def test_missing_reordered_or_incorrect_observations_fail(self):
        cases = [{'output_int': [1, 2, 3, 4]}]
        valid = {'case': '0', 'cycles': '270', 'stalls': '6', 'o0': '1', 'o1': '2', 'o2': '3', 'o3': '4'}
        for rows in [[], [dict(valid, case='1')], [dict(valid, o2='4')], [dict(valid, cycles='269')]]:
            with self.subTest(rows=rows), self.assertRaises(RuntimeError):
                runner.Experiment.verify_rows(None, cases, rows, 'test')
        runner.Experiment.verify_rows(None, cases, [valid], 'test')


if __name__ == '__main__':
    unittest.main()
