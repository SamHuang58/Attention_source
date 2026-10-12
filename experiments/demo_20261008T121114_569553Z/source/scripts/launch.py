"""Portable source-only launchers. No report or replay dependencies."""
from pathlib import Path
import argparse
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['full', 'quick', 'custom', 'algorithm'])
args = parser.parse_args()
local_python = ROOT / 'tools/research-env/Scripts/python.exe'
python = str(local_python) if local_python.exists() else sys.executable
env = os.environ.copy()
env['PYTHONIOENCODING'] = 'utf-8'
env['PATH'] = str(ROOT / 'tools/research-env/Scripts') + os.pathsep + env.get('PATH', '')
commands = {
    'full': ['scripts/run_research.py'],
    'quick': ['scripts/run_research.py', '--seeds', '20260922', '--random', '32', '--groups', '4', '--skip-netlist'],
    'custom': ['scripts/run.py', '--input', 'docs/demo_input.json', '--synth'],
    'algorithm': ['model/golden.py', '--input', 'docs/demo_input.json'],
}
raise SystemExit(subprocess.call([python, *commands[args.mode]], cwd=ROOT, env=env))
