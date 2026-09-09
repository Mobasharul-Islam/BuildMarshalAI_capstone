import json, sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def main():
    root = Path(__file__).resolve().parents[1]
    nb_path = root / "backend" / "Local_Working_with_Document_Generation_CLIProxyAPI.ipynb"
    
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    print(f"Loaded notebook with {len(nb['cells'])} cells.")
    
    # We create a shared execution namespace
    ns = {"__name__": "__main__", "__file__": str(nb_path)}
    
    for i, cell in enumerate(nb["cells"]):
        if cell.get("cell_type") != "code":
            continue
        # Skip cell 13 (blocking uvicorn server) during test
        if i == 13:
            print(f"\nSkipping Cell 13 (start_server) during batch validation.")
            continue
        
        src = "".join(cell.get("source", []))
        if not src.strip():
            continue
        
        print(f"\n==================================================", flush=True)
        print(f"Executing Cell {i} ...", flush=True)
        print(f"--------------------------------------------------", flush=True)
        
        try:
            exec(src, ns)
            print(f"Cell {i} executed successfully!", flush=True)
        except Exception as e:
            print(f"FAILED on Cell {i}: {type(e).__name__}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            sys.exit(1)
            
    print("\n==================================================")
    print("ALL CELLS (0 to 12) EXECUTED SUCCESSFULLY WITHOUT ERRORS!")
    print("==================================================")

if __name__ == "__main__":
    main()
