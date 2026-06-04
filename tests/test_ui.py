#!/usr/bin/env python3
import os
import sys
import argparse
import tempfile
import shutil
import subprocess
from datetime import datetime, timedelta

def main():
    parser = argparse.ArgumentParser(description="Diagnostic test for Posture Reminder UI")
    parser.add_argument("--no-data", action="store_true", help="Test with no ratings data")
    parser.add_argument("--with-data", action="store_true", help="Test with dummy ratings data")
    args = parser.parse_args()

    # Determine project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
        print(f"Launching reminder UI...")
        mock_file = os.path.join(project_root, "posture_ratings_mock.txt")
        shutil.copy2(temp_path, mock_file)
        
        backup_path = original_ratings + ".bak"
        if os.path.exists(original_ratings):
            shutil.move(original_ratings, backup_path)
            
        try:
            shutil.copy2(mock_file, original_ratings)
            subprocess.run(
                [sys.executable, os.path.join(project_root, "notifications.py"), "posture", "--wait", "1", "--timeout", "10"],
                cwd=project_root
            )
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
