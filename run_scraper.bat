@echo off
REM Spousti scraper pythonem z venv a zapisuje vystup do logu.
REM Task Scheduler nic nezobrazi, takze bez logu nepozname, jestli beh dopadl dobre.

cd /d "C:\Users\Ondra\Desktop\Data\Projekty\Scraper_AI"

echo ==== START %date% %time% ==== >> scraper_log.txt
set PYTHONUTF8=1
"C:\Users\Ondra\Desktop\Data\Projekty\Scraper_AI\venv\Scripts\python.exe" -u load_to_supabase.py >> scraper_log.txt 2>&1
set EXITCODE=%errorlevel%
echo ==== KONEC %date% %time% (exit code: %EXITCODE%) ==== >> scraper_log.txt
echo. >> scraper_log.txt

exit /b %EXITCODE%