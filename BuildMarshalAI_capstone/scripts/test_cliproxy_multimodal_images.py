"""Independent CLIProxyAPI multimodal smoke test using four local screenshots.

This script does not start the BuildMarshalAI backend or load ColPali. It sends
each screenshot directly to the OpenAI-compatible CLIProxyAPI endpoint, saves
the model descriptions, and performs lightweight content checks.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.cliproxy_client import CLIProxyClient  # noqa: E402


TEST_CASES = [
    {
        "path": Path(r"C:\Users\MSI RAIDER GE77\OneDrive\Pictures\Screenshots\Screenshot 2026-08-17 024820.png"),
        "anchors": ["excel", "drift", "table"],
    },
    {
        "path": Path(r"C:\Users\MSI RAIDER GE77\OneDrive\Pictures\Screenshots\Screenshot 2026-08-17 030955.png"),
        "anchors": ["chatgpt plus", "billing", "telegram"],
    },
    {
        "path": Path(r"C:\Users\MSI RAIDER GE77\OneDrive\Pictures\Screenshots\Screenshot 2026-08-17 214806.png"),
        "anchors": ["billing", "chatgpt plus", "paused", "transaction"],
    },
    {
        "path": Path(r"C:\Users\MSI RAIDER GE77\OneDrive\Pictures\Screenshots\Screenshot 2026-08-17 214917.png"),
        "anchors": ["power increase in maths", "trigonometric integral steps", "zachary jenkins"],
    },
]


def load_local_proxy_environment() -> None:
    os.environ.setdefault("CLIPROXY_BASE_URL", "http://127.0.0.1:8317/v1")
    os.environ.setdefault("CLIPROXY_MODEL", "gemini-3.7-flash-high")
    if os.environ.get("CLIPROXY_API_KEY"):
        return
    config = Path.home() / ".cli-proxy-api" / "config.yaml"
    if not config.exists():
        raise RuntimeError(f"CLIProxyAPI config not found: {config}")
    match = re.search(
        r"(?m)^api-keys:\s*\r?\n\s*-\s*[\"']?([^\"'\r\n#]+)",
        config.read_text(encoding="utf-8"),
    )
    if not match:
        raise RuntimeError("No api-keys entry was found in the CLIProxyAPI config")
    os.environ["CLIPROXY_API_KEY"] = match.group(1).strip()


def main() -> int:
    load_local_proxy_environment()
    client = CLIProxyClient()
    output_dir = ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for index, case in enumerate(TEST_CASES, 1):
        path = case["path"]
        if not path.exists():
            raise FileNotFoundError(path)
        prompt = (
            "Describe this screenshot accurately and in detail. Identify the application or interface, "
            "the main visible content, important labels and readable text, tables or panels, and the "
            "overall layout. Do not infer anything that is not visible."
        )
        description, model = client.chat(
            [{
                "role": "user",
                "content": [
                    {"type": "image", "image": str(path)},
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=1200,
        )
        normalized = description.casefold()
        matched = [anchor for anchor in case["anchors"] if anchor in normalized]
        passed = len(matched) >= max(2, len(case["anchors"]) - 1)
        result = {
            "image": str(path),
            "model": model,
            "description": description,
            "expected_anchors": case["anchors"],
            "matched_anchors": matched,
            "passed": passed,
        }
        results.append(result)
        print(f"[{index}/4] {'PASS' if passed else 'FAIL'} - {path.name}")
        print(description)
        print()

    json_path = output_dir / "cliproxy_multimodal_image_test.json"
    markdown_path = output_dir / "cliproxy_multimodal_image_test.md"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown = ["# CLIProxyAPI multimodal image test", ""]
    for index, result in enumerate(results, 1):
        markdown.extend([
            f"## Image {index}: {Path(result['image']).name}",
            "",
            f"- Result: **{'PASS' if result['passed'] else 'FAIL'}**",
            f"- Model: `{result['model']}`",
            f"- Matched checks: {', '.join(result['matched_anchors']) or 'none'}",
            "",
            result["description"],
            "",
        ])
    markdown_path.write_text("\n".join(markdown), encoding="utf-8")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
