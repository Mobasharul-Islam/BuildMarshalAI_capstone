import json, sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def main():
    root = Path(__file__).resolve().parents[1]
    nb_path = root / "backend" / "Local_Working_with_Document_Generation_CLIProxyAPI.ipynb"
    
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    print(f"Total cells in notebook: {len(nb['cells'])}")
    for i, cell in enumerate(nb["cells"]):
        ctype = cell.get("cell_type")
        src = "".join(cell.get("source", []))
        first_lines = src.strip().split("\n")[:2] if src.strip() else ["(empty)"]
        outputs = cell.get("outputs", [])
        has_error = any(o.get("output_type") == "error" for o in outputs)
        
        print(f"\n==================================================")
        print(f"CELL {i} [{ctype}] | Output count: {len(outputs)} | Has Error: {has_error}")
        print(f"Preview: {' | '.join(first_lines)}")
        print(f"--------------------------------------------------")
        
        for j, out in enumerate(outputs):
            out_type = out.get("output_type")
            if out_type == "stream":
                text = "".join(out.get("text", []))
                print(f"  [Output {j} Stream/{out.get('name')}]:\n{text[:400]}")
                if len(text) > 400:
                    print(f"  ... ({len(text)} chars total)")
            elif out_type == "error":
                ename = out.get("ename")
                evalue = out.get("evalue")
                print(f"  [Output {j} ERROR]: {ename} - {evalue}")
                for tb in out.get("traceback", []):
                    print(f"    {tb}")
            elif out_type in ("execute_result", "display_data"):
                data = out.get("data", {})
                if "text/plain" in data:
                    print(f"  [Output {j} {out_type} text/plain]: {''.join(data['text/plain'])[:200]}")
                else:
                    print(f"  [Output {j} {out_type} keys]: {list(data.keys())}")

if __name__ == "__main__":
    main()
