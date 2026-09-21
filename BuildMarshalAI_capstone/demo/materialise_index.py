"""Put a real indexed workspace on disk, so storage measures real files.

The storage panel reports what is actually there. Against an empty workspace it
honestly reports nothing, which demonstrates nothing -- so this renders the
pack's PDFs to page images for real, and writes multi-vector caches and vision
tiles at the sizes ColPali actually produces.

It also leaves behind exactly what a workspace accumulates in use:

* **orphans** -- caches and tiles for a document that was deleted, which are
  keyed by page filename and so outlive it;
* **a duplicate** -- the same specification uploaded again under another name,
  byte for byte.

Both are what a sweep then reclaims, and neither is invented: the sweep finds
them by looking.

    python demo/materialise_index.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / ".demo-runtime"
PACK = HERE / "project-pack"

#: ColPali v1.2 emits roughly this many patch vectors per page, at 128 dims.
PATCHES, DIMS = 1030, 128
#: Pages are rendered at this longest edge, matching the ingest pipeline.
PAGE_EDGE = 1400


def page_image(document: fitz.Document, index: int, target: Path) -> int:
    """Render one PDF page the way the ingest pipeline does."""
    page = document[index]
    scale = PAGE_EDGE / max(page.rect.width, page.rect.height)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    image.save(target, "WEBP", quality=82, method=4)
    return target.stat().st_size


def sheet_image(text: str, target: Path, pages: int = 1) -> int:
    """A stand-in page for a document type that is not a PDF."""
    from PIL import ImageDraw

    image = Image.new("RGB", (990, PAGE_EDGE), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([40, 40, 950, 120], fill="#1f2933")
    draw.text((60, 70), text[:60], fill="white")
    for row in range(26):
        y = 170 + row * 44
        draw.line([(40, y), (950, y)], fill="#dfe3e8", width=2)
        draw.text((60, y - 26), f"row {row + 1}", fill="#5a636b")
    image.save(target, "WEBP", quality=82, method=4)
    return target.stat().st_size


def multivector(target: Path) -> int:
    """A cache the size ColPali really writes: 1030 x 128 at float16."""
    rng = np.random.default_rng(abs(hash(target.name)) % (2**32))
    vectors = rng.standard_normal((PATCHES, DIMS), dtype=np.float32).astype(np.float16)
    np.save(target, vectors)
    return target.stat().st_size


def tile(target: Path) -> int:
    rng = np.random.default_rng(abs(hash(target.name)) % (2**32))
    noise = rng.integers(96, 224, (512, 396, 3), dtype=np.uint8)
    Image.fromarray(noise).save(target, "JPEG", quality=70)
    return target.stat().st_size


def main() -> None:
    marker = RUNTIME / "seeded.json"
    if not marker.exists():
        sys.exit("Run the demonstration backend once first, so the account exists.")
    account_id = json.loads(marker.read_text())["account_id"]
    root = RUNTIME / "accounts" / account_id
    if not root.exists():
        candidates = [p for p in RUNTIME.rglob("metadata.json")]
        if not candidates:
            sys.exit(f"No workspace found under {RUNTIME}")
        root = candidates[0].parent

    docs = root / "documents"
    pages = root / "pages"
    vectors = root / "colpali_v1_2_multivectors"
    tiles = root / "document_generation_vision_cache"
    for directory in (docs, pages, vectors, tiles):
        directory.mkdir(parents=True, exist_ok=True)

    meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    documents = meta.get("documents", {})
    written = {"pages": 0, "vectors": 0, "tiles": 0, "bytes": 0}

    for doc_id, document in documents.items():
        name = document["name"]
        source = PACK / name
        if source.exists():
            shutil.copy2(source, docs / f"{doc_id}_{name}")
            document["size"] = source.stat().st_size

        pdf = fitz.open(source) if source.suffix.lower() == ".pdf" and source.exists() else None
        count = pdf.page_count if pdf else int(document.get("page_count", 1))
        document["page_count"] = count
        document["pages"] = []

        for number in range(1, count + 1):
            stem = f"{doc_id}_page_{number}"
            image = pages / f"{stem}.webp"
            size = (page_image(pdf, number - 1, image) if pdf
                    else sheet_image(f"{name} — sheet {number}", image))
            written["pages"] += 1
            written["bytes"] += size
            written["bytes"] += multivector(vectors / f"{stem}.npy")
            written["vectors"] += 1
            if number <= 2:  # tiles are only made for pages a generation read
                written["bytes"] += tile(tiles / f"{stem}_512.jpg")
                written["tiles"] += 1
            document["pages"].append(
                {"page_num": number, "image_path": str(image), "text_content": ""})
        if pdf:
            pdf.close()

    # What a workspace accumulates: a deleted document's caches, which are keyed
    # by page filename and so were never reachable to delete.
    ghost = "d0ead0cumen7"
    for number in range(1, 15):
        stem = f"{ghost}_page_{number}"
        written["bytes"] += multivector(vectors / f"{stem}.npy")
        written["bytes"] += tile(tiles / f"{stem}_512.jpg")

    # Digests are what dedup matches on, so they must be the real bytes.
    for doc_id, document in list(documents.items()):
        stored = docs / f"{doc_id}_{document['name']}"
        if stored.exists():
            document["digest"] = hashlib.sha256(stored.read_bytes()).hexdigest()

    # The same specification, issued again under a construction-issue name and
    # indexed a second time -- the single commonest way a workspace doubles.
    original = next((doc_id for doc_id, d in documents.items()
                     if d["name"] == "06_Dorpotro-Bibaroni_Tender-Specification.pdf"), "")
    if original and not any(d["name"].startswith("Dorpotro-Bibaroni_IFC")
                            for d in documents.values()):
        copy_id = "dup" + original[:9]
        source = docs / f"{original}_{documents[original]['name']}"
        name = "Dorpotro-Bibaroni_IFC-RevC.pdf"
        shutil.copy2(source, docs / f"{copy_id}_{name}")
        pages_of = []
        with fitz.open(source) as pdf:
            for number in range(1, pdf.page_count + 1):
                stem = f"{copy_id}_page_{number}"
                image = pages / f"{stem}.webp"
                page_image(pdf, number - 1, image)
                multivector(vectors / f"{stem}.npy")
                pages_of.append({"page_num": number, "image_path": str(image),
                                 "text_content": ""})
        documents[copy_id] = {
            **documents[original], "id": copy_id, "name": name,
            "pages": pages_of, "page_count": len(pages_of),
            "digest": documents[original]["digest"]}

    (root / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    print(f"  {written['pages']:>3} page images")
    print(f"  {written['vectors']:>3} multi-vector caches")
    print(f"  {written['tiles']:>3} vision tiles")
    print(f"   14 orphaned caches + 14 orphaned tiles (a document that was deleted)")
    print(f"\n  workspace now {total / 1024 / 1024:.1f} MB on disk")


if __name__ == "__main__":
    main()
