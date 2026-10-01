"""Strip the standalone wrapper so the page can be published as an Artifact.

site/index.html is a complete document, so it can be opened from disk or served
from any static host. The Artifact platform supplies its own doctype, html,
head and body, so publishing that file verbatim would nest a document inside a
document. One source, two shapes.

    python site/build_artifact.py     # writes site/_artifact.html
"""
from __future__ import annotations

import io
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
source = io.open(HERE / "index.html", encoding="utf-8", newline="").read()

head = re.search(r"<head>(.*?)</head>", source, re.S).group(1)
body = re.search(r"<body>(.*?)</body>", source, re.S).group(1)

# The skeleton already carries charset and viewport; everything else is ours.
head = re.sub(r"<meta\s+charset[^>]*>\s*", "", head)
head = re.sub(r'<meta\s+name="viewport"[^>]*>\s*', "", head)

out = HERE / "_artifact.html"
io.open(out, "w", encoding="utf-8", newline="\n").write(head.strip() + "\n" + body.strip() + "\n")
print(f"  {out.name}  {out.stat().st_size / 1024:.0f} KB")
