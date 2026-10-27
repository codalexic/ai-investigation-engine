import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.cli import benchmark_main

if __name__ == "__main__":
    benchmark_main()
