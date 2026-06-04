#!/usr/bin/env python3
import sys
import os

# Set working directory to project root and execute from tests/
script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, script_dir)

from tests.test_ui import main

if __name__ == "__main__":
    main()
