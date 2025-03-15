# PowerShell script to clear the phantom task
# Usage: .\clear_phantom_task.ps1 [task_id]

param (
    [string]$TaskId = "aeb14b2e-c824-4f5a-9edf-8ba44eaaa25b"
)

Write-Host "=== Phantom Task Cleaner Utility ==="
Write-Host "This utility will attempt to clear a specific phantom task from RabbitMQ"
Write-Host ""
Write-Host "Target task ID: $TaskId"
Write-Host ""

# Check if Python is available
try {
    $pythonVersion = python --version
    Write-Host "Using Python: $pythonVersion"
}
catch {
    Write-Host "ERROR: Python not found. Please install Python 3.6+ to continue." -ForegroundColor Red
    exit 1
}

# Check if necessary packages are installed
Write-Host "Checking required packages..."
python -m pip install requests pika -q

# Run the cleaner script
Write-Host ""
Write-Host "Running phantom task cleaner..."
python clear_phantom.py --task-id $TaskId

# Check if the script succeeded
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Success! The phantom task was found and cleared." -ForegroundColor Green
    
    # Restart Celery workers
    Write-Host ""
    Write-Host "Would you like to restart Celery workers? (y/n)"
    $restart = Read-Host
    
    if ($restart -eq "y") {
        Write-Host "Restarting Celery workers..."
        
        # First try to gracefully stop workers
        try {
            # Find Celery processes
            $celeryProcesses = Get-Process -Name "celery" -ErrorAction SilentlyContinue
            
            if ($celeryProcesses) {
                Write-Host "Stopping existing Celery workers..."
                Stop-Process -Name "celery" -Force
                Start-Sleep -Seconds 2
            }
            
            # Start new workers
            Write-Host "Starting new Celery workers..."
            Start-Process -FilePath "celery" -ArgumentList "-A cel_main worker --loglevel=info" -NoNewWindow
            
            Write-Host "Celery workers restarted successfully." -ForegroundColor Green
        }
        catch {
            Write-Host "Error restarting Celery workers. Please restart them manually." -ForegroundColor Yellow
            Write-Host "Command: celery -A cel_main worker --loglevel=info"
        }
    }
    
    Write-Host ""
    Write-Host "Operation completed. The phantom task has been cleared." -ForegroundColor Green
}
else {
    Write-Host ""
    Write-Host "The phantom task could not be found or removed." -ForegroundColor Yellow
    Write-Host "Try using the recover_tasks.py utility to inspect the queue:"
    Write-Host "  python recover_tasks.py"
    
    # Offer to force purge the entire queue
    Write-Host ""
    Write-Host "Would you like to force purge the entire queue? This will remove ALL messages. (y/n)"
    $purge = Read-Host
    
    if ($purge -eq "y") {
        Write-Host "Running queue purge..."
        python recover_tasks.py purge
    }
}

Write-Host ""
Write-Host "Done." 