@echo off
:: Memory reconciliation scheduled task wrapper
:: Run this every 5 minutes via Task Scheduler
:: Resolves the script next to this .bat so it works from any clone location.
python "%~dp0reconcile_memory.py"
