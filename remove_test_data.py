#!/usr/bin/env python3
import subprocess
import sys
import os

def run_cmd(cmd, cwd=None, capture=True, timeout=300):
    """Run command and return result."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True, timeout=timeout)
    return result

# Remove test_data from working directory
print("Removing test_data from working directory...")
result = run_cmd(['rm', '-rf', 'test_data'], cwd='/home/matti/Kodowanie/Firefly III')
print(f"rm -rf test_data: {result.returncode}")

# Remove test_data from git index
print("Removing test_data from git index...")
result = run_cmd(['git', 'ls-files', 'test_data/'], cwd='/home/matti/Kodowanie/Firefly III')
files = result.stdout.strip().split('\n')
for f in files:
    if f:
        run_cmd(['git', 'rm', '--cached', f], cwd='/home/matti/Kodowanie/Firefly III')
print("Done removing from index")

# Check status
result = run_cmd(['git', 'status', '--porcelain'], cwd='/home/matti/Kodowanie/Firefly III')
print(f"Status: {result.stdout[:500]}")

# Use git filter-branch
print("Running git filter-branch...")
result = run_cmd([
    'git', 'filter-branch', '-f',
    '--index-filter', 'git rm -rf --cached --ignore-unmatch test_data',
    '--prune-empty',
    '--tag-name-filter', 'cat',
    '--', '--all'
], cwd='/home/matti/Kodowanie/Firefly III', timeout=600)
print(f"filter-branch stdout: {result.stdout}")
print(f"filter-branch stderr: {result.stderr}")
print(f"filter-branch returncode: {result.returncode}")

# Check if test_data is gone from history
result = run_cmd(['git', 'log', '--oneline', '--all', '--', 'test_data/'], cwd='/home/matti/Kodowanie/Firefly III')
print(f"test_data in history: {result.stdout}")