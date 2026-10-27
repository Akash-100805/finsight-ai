"""
Pytest configuration for TKG tests.
Adds services/tkg/src and shared to PYTHONPATH.
"""
import os
import sys

tests_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(tests_dir, "..", "..", ".."))

src_dir = os.path.join(repo_root, "services", "tkg", "src")
shared_dir = os.path.join(repo_root, "shared")

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

if shared_dir not in sys.path:
    sys.path.insert(0, shared_dir)
