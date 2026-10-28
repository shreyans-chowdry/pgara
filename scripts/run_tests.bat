@echo off
cd /d "%~dp0\.."
python -m unittest -v tests.test_compiler
