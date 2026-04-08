import os
import sys
from pathlib import Path

# Before tribev2/neuralset import: DataLoader workers + fork can trigger torch.cuda on
# CPU-only macOS wheels; keep workers at 0 for the whole test session unless overridden.
os.environ.setdefault("TRIBEV2_NUM_WORKERS", "0")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
