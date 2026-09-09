from __future__ import annotations
import json
from pathlib import Path

def main():
    root = Path(__file__).resolve().parents[1]
    nb_path = root / "backend" / "Local_Working_with_Document_Generation_CLIProxyAPI.ipynb"
    out_path = root / "backend" / "run_backend.py"

    with open(nb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    header = '''from __future__ import annotations
# Auto-generated backend runner for BuildMarshalAI
import os, sys
from pathlib import Path

# Force UTF-8 stdout and stderr encoding on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

backend_dir = Path(__file__).resolve().parent
repo_root = backend_dir.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(repo_root))
os.chdir(str(backend_dir))
'''

    script_lines = [header]

    for i, cell in enumerate(nb["cells"]):
        if cell["cell_type"] == "code":
            if i in (1, 2):
                continue
            source = "".join(cell["source"])
            if not source.strip():
                continue
            cleaned_lines = []
            for line in source.splitlines():
                if line.strip().startswith("from __future__ import"):
                    continue
                cleaned_lines.append(line)
            script_lines.append(f"\n# {'='*70}\n# CELL {i}\n# {'='*70}\n")
            script_lines.append("\n".join(cleaned_lines) + "\n")

    out_path.write_text("\n".join(script_lines), encoding="utf-8")
    print(f"Successfully generated {out_path}")

if __name__ == "__main__":
    main()
