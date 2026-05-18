#!/usr/bin/env python3
import os
import argparse
import tempfile
import shutil
from datetime import datetime, timedelta

def main():
    parser = argparse.ArgumentParser(description="Diagnostic test for Posture Reminder UI")
    parser.add_argument("--no-data", action="store_true", help="Test with no ratings data")
    parser.add_argument("--with-data", action="store_true", help="Test with dummy ratings data")
    args = parser.parse_args()

    # Determine project root
    project_root = os.path.dirname(os.path.abspath(__file__))
    original_ratings = os.path.join(project_root, "posture_ratings.txt")
    
    # Use a temporary file for ratings to avoid messing with real data
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False) as tmp:
        temp_path = tmp.name
        if args.with_data:
            print("Creating dummy data for plot...")
            now = datetime.now()
            # Generate 10 ratings in ascending order
            for i in range(9, -1, -1):
                time_str = (now - timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S")
                rating = ((10-i) % 5) + 1
                tmp.write(f"{time_str} - Rating: {rating}\n")
        elif args.no_data:
            print("Testing with no data (empty file)...")
            pass
        else:
            print("Please specify --no-data or --with-data")
            return

    try:
        # Override the ratings file path in notifications.py temporarily
        # We'll do this by calling notifications.py with a modified environment or just passing the path
        print(f"Launching reminder UI...")
        import subprocess
        import sys
        
        # We need to tell notifications.py to use our temp file
        # Since notifications.py hardcodes ratings_file_path at the top level, 
        # we'll use a little trick: copy our temp file to a known name and use it
        mock_file = os.path.join(project_root, "posture_ratings_mock.txt")
        shutil.copy2(temp_path, mock_file)
        
        # We need a small patch to notifications.py to accept an override if we want to be clean,
        # but for a quick test, we can just edit the file or rely on the mock name if we modified it.
        # Actually, let's just run it and manually verify.
        
        # NOTE: This test script assumes notifications.py has been modified to look for a mock file if it exists,
        # OR we just temporarily swap the real one. Let's swap the real one safely.
        
        backup_path = original_ratings + ".bak"
        if os.path.exists(original_ratings):
            shutil.move(original_ratings, backup_path)
            
        try:
            shutil.copy2(mock_file, original_ratings)
            subprocess.run([sys.executable, "notifications.py", "posture", "--wait", "1", "--timeout", "10"])
        finally:
            if os.path.exists(backup_path):
                shutil.move(backup_path, original_ratings)
            if os.path.exists(mock_file):
                os.remove(mock_file)
                
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

if __name__ == "__main__":
    main()
