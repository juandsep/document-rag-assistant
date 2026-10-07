"""Delete old Qdrant index versions, keeping what a rollback needs.

Usage:
    uv run --env-file .env python scripts/prune_versions.py [--keep-previous 1] [--yes]

Keeps the version the alias serves, every newer version (candidates still
waiting for their evaluation) and the --keep-previous newest older ones.
Without --yes it only lists what it would delete. Deleting is permanent.
"""

from __future__ import annotations

import argparse

from rag.retrievers import QdrantRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--keep-previous", type=int, default=1)
    parser.add_argument("--yes", action="store_true", help="really delete")
    args = parser.parse_args()

    retriever = QdrantRetriever()
    doomed = retriever.prune(args.keep_previous, dry_run=not args.yes)
    print(f"serving: {retriever._serving()}")
    verb = "deleted" if args.yes else "would delete (rerun with --yes)"
    print(f"{verb}: {', '.join(doomed) or 'nothing'}")


if __name__ == "__main__":
    main()
