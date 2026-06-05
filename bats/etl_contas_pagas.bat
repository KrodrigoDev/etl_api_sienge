@echo off
chcp 65001 > nul
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

cd /d C:\Users\kaua.rodrigo\PycharmProjects\etl_api_sienge

if not exist logs mkdir logs

echo ========================================= >> logs\contas_pagas_execucao.log
echo INICIO %date% %time% >> logs\contas_pagas_execucao.log
echo ========================================= >> logs\contas_pagas_execucao.log

C:\Users\kaua.rodrigo\PycharmProjects\etl_api_sienge\.venv\Scripts\python.exe main.py >> logs\contas_pagas_execucao.log 2>&1

echo FIM %date% %time% >> logs\contas_pagas_execucao.log