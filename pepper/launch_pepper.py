#!/usr/bin/env python
"""
Wrapper script to run the scheduler with suppressed MCP banner output.
"""
import os
import subprocess
import sys
from pathlib import Path


# Add the parent directory to Python path so we can import pepper
sys.path.insert(0, str(Path(__file__).parent.parent))

from pepper.constants import REPO_ROOT

# Set environment variables
os.environ["PYTHONWARNINGS"] = "ignore::RuntimeWarning"
# Ensure Python path includes the parent directory
parent_dir = str(Path(__file__).parent.parent)
if "PYTHONPATH" in os.environ:
    os.environ["PYTHONPATH"] = f"{parent_dir}:{os.environ['PYTHONPATH']}"
else:
    os.environ["PYTHONPATH"] = parent_dir

# Run the scheduler with stderr redirected
process = subprocess.Popen(
    [sys.executable, "-m", "pepper.agent.scheduler"],
    # stderr=subprocess.DEVNULL,  # Suppress stderr (where banners are printed)
    stdout=None,  # Keep stdout for normal output
    cwd=REPO_ROOT,
    env=os.environ.copy(),  # Pass current environment to subprocess
)

important_email_process = subprocess.Popen(
    [sys.executable, "-m", "pepper.feed.important_email"],
    stderr=subprocess.DEVNULL,  # Suppress stderr (where banners are printed)
    stdout=None,  # Keep stdout for normal output
    cwd=REPO_ROOT,
    env=os.environ.copy(),  # Pass current environment to subprocess
)

user_profile_process = subprocess.Popen(
    [sys.executable, "-m", "pepper.feed.user_profile"],
    stderr=subprocess.DEVNULL,  # Suppress stderr (where banners are printed)
    stdout=None,  # Keep stdout for normal output
    cwd=REPO_ROOT,
    env=os.environ.copy(),  # Pass current environment to subprocess
)

reminder_process = subprocess.Popen(
    [
        "uvicorn",
        "pepper.services.reminder_http:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8060",
    ],
    # stderr=subprocess.DEVNULL,  # Suppress stderr (where banners are printed)
    stdout=None,  # Keep stdout for normal output
    cwd=REPO_ROOT,
    env=os.environ.copy(),  # Pass current environment to subprocess
)

email_service_process = subprocess.Popen(
    [sys.executable, "-m", "pepper.services.email_service"],
    # stderr=subprocess.DEVNULL,
    stdout=None,
    cwd=REPO_ROOT,
    env=os.environ.copy(),
)

ui_process = subprocess.Popen(
    ["python", "-m", "http.server", "5050", "--bind", "0.0.0.0"],
    cwd=REPO_ROOT,
    env=os.environ.copy(),  # Pass current environment to subprocess
)

try:
    process.wait()
except KeyboardInterrupt:
    print("\n[LAUNCH] Shutting down Pepper...")

    # First try SIGINT for the scheduler (gentler, like Ctrl+C)
    try:
        process.send_signal(2)  # SIGINT
        process.wait(timeout=5)  # Wait up to 5 seconds
        print("[LAUNCH] Scheduler stopped gracefully")
    except subprocess.TimeoutExpired:
        print("[LAUNCH] Scheduler didn't respond to SIGINT, sending SIGTERM...")
        process.terminate()
        process.wait()

    # Terminate other processes
    user_profile_process.terminate()
    important_email_process.terminate()
    reminder_process.terminate()
    email_service_process.terminate()
    ui_process.terminate()

    # Wait for them to finish
    user_profile_process.wait()
    important_email_process.wait()
    reminder_process.wait()
    email_service_process.wait()
    ui_process.wait()

    print("[LAUNCH] All processes stopped.")
finally:
    os.system("pkill -f 'pepper.'")
    os.system("pkill -f 'http.server 5050'")
