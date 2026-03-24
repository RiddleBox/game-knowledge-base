@echo off
cd /d D:\AIproject\game-knowledge-base
echo [%date% %time%] 开始采集...

"C:\Program Files\Python314\python.exe" D:\AIproject\game-knowledge-base\scripts\daily_intel_collector.py

echo [%date% %time%] 采集完成，推送到GitHub...
git add 00-Inbox\
git commit -m "auto: daily intel %date%"
git push

echo [%date% %time%] 完成！
