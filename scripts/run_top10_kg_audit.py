from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kg_top10 import run_audit


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    result = run_audit(root)
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
