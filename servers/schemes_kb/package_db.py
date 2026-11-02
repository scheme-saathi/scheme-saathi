"""Package the approved ChromaDB collections as a zip for a GitHub Release.

Copies only approved records (no draft review collection, no draft PDF chunks) into a
fresh database, adds MANIFEST.json, zips it as dist/chroma-<date>.zip, then reopens the
zip's copy to check it. Teammates unzip it into data/ instead of re-importing.
"""

import argparse
import json
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import chromadb
from chromadb.errors import NotFoundError

from servers.schemes_kb.import_schemes import COLLECTION_NAME, DB_PATH, MODEL_NAME
from servers.schemes_kb.preview_chunks import PROJECT_ROOT
from servers.schemes_kb.search import PDF_COLLECTION_NAME


def git(*args):
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout.strip()


def copy_approved(source, target):
    counts = {}
    for name in (COLLECTION_NAME, PDF_COLLECTION_NAME):
        try:
            old = source.get_collection(name, embedding_function=None)
        except NotFoundError:
            continue
        if (old.metadata or {}).get("model") != MODEL_NAME:
            raise ValueError(f"Embedding model differs in {name}.")
        rows = old.get(where={"review_status": "approved"}, include=["embeddings", "documents", "metadatas"])
        new = target.create_collection(name, embedding_function=None, metadata=old.metadata,
                                       configuration={"hnsw": {"space": "cosine"}})
        for start in range(0, len(rows["ids"]), 500):
            end = start + 500
            new.add(ids=rows["ids"][start:end], embeddings=rows["embeddings"][start:end],
                    documents=rows["documents"][start:end], metadatas=rows["metadatas"][start:end])
        counts[name] = len(rows["ids"])
    if not counts.get(COLLECTION_NAME):
        raise ValueError("No approved scheme chunks found. Run import_schemes first.")
    return counts


def check_zip(archive, counts):
    # Reopen the packaged copy the way a teammate would and query it with a stored vector.
    with tempfile.TemporaryDirectory() as folder:
        zipfile.ZipFile(archive).extractall(folder)
        client = chromadb.PersistentClient(path=str(Path(folder) / "chroma"))
        for name, count in counts.items():
            collection = client.get_collection(name, embedding_function=None)
            assert collection.count() == count, f"{name}: {collection.count()} != {count}"
        pages = client.get_collection(COLLECTION_NAME, embedding_function=None)
        sample = pages.get(limit=1, include=["embeddings"])
        hit = pages.query(query_embeddings=[sample["embeddings"][0]], n_results=1)
        assert hit["ids"][0][0] == sample["ids"][0], "Packaged index returned the wrong nearest match."


def main():
    parser = argparse.ArgumentParser(description="Zip approved ChromaDB collections for sharing.")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "dist")
    args = parser.parse_args()
    if git("status", "--porcelain", "--", "data/schemes"):
        parser.error("data/schemes has uncommitted changes. Commit them first so the zip matches a commit.")
    if not (DB_PATH / "chroma.sqlite3").exists():
        parser.error("Database not found. Run python -m servers.schemes_kb.import_schemes first.")

    archive = args.out / f"chroma-{date.today().isoformat()}.zip"
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "chroma"
        counts = copy_approved(chromadb.PersistentClient(path=str(DB_PATH)),
                               chromadb.PersistentClient(path=str(target)))
        manifest = {
            "created_on": date.today().isoformat(), "git_commit": git("rev-parse", "HEAD"),
            "model": MODEL_NAME, "chromadb_version": chromadb.__version__, "collections": counts,
            "schemes": len({m["scheme_id"] for m in chromadb.PersistentClient(path=str(target))
                            .get_collection(COLLECTION_NAME).get(include=["metadatas"])["metadatas"]}),
        }
        (target / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=folder, base_dir="chroma")
    check_zip(archive, counts)
    print(json.dumps(manifest, indent=2))
    print(f"Saved and checked {archive} ({archive.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
