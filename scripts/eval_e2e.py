import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.cli import e2e_main

if __name__ == "__main__":
    e2e_main()
