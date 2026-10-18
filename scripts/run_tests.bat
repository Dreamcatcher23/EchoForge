@echo off
echo === EchoForge Test Suite ===
cd %~dp0..
python -m pytest tests/ -v --tb=short
echo === Tests complete ===
