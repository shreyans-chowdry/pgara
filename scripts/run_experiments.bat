@echo off
cd /d "%~dp0\.."
python -m pgara.experiments %* --config configs\experiments.json --out results\v2
python scripts\summarise_results.py
