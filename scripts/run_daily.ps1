Set-Location "D:\AIproject\game-knowledge-base"

Write-Host "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] Starting daily intel collection..."

& "C:\Program Files\Python314\python.exe" "D:\AIproject\game-knowledge-base\scripts\daily_intel_collector.py"

Write-Host "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] Collection done. Pushing to GitHub..."

git add "00-Inbox\"
git add "01-Briefs\"
$dateStr = (Get-Date).ToString("yyyy-MM-dd")
git commit -m "auto: daily intel $dateStr"
git pull --rebase origin master
git push

Write-Host "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] Done!"
