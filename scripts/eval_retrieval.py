import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.cli import retrieval_main

if __name__ == "__main__":
    retrieval_main()
