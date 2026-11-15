#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Run test_wzorce.py
exec(open("test_wzorce.py").read())

if __name__ == '__main__':
    sys.exit(main())