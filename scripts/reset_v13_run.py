from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_history import archive_and_reset_run


def main() -> None:
    manifest = archive_and_reset_run()
    archived = ", ".join(entry["archived"] for entry in manifest["archived_files"]) or "no existing files"
    print(f"Archived and reset run history: {archived}")


if __name__ == "__main__":
    main()
