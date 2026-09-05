import pandas as pd
from pathlib import Path
import subprocess
import shutil
import os
import sys

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()

AUDIT = ROOT / "csv_dataset" / "objective1_bookstore_strict_inplace_repair_source_audit.csv"
BACKUP = ROOT / "csv_dataset" / "objective1_bookstore_strict_inplace_repair_source_audit_FULL_BACKUP.csv"

START = int(sys.argv[1]) if len(sys.argv) > 1 else 100
COUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 50

JAVA_HOME_FIXED = os.environ.get("JAVA_HOME", "")

env = os.environ.copy()
env["JAVA_HOME"] = JAVA_HOME_FIXED
env["PATH"] = str(Path(JAVA_HOME_FIXED) / "bin") + os.pathsep + env.get("PATH", "")

# Prefer the full backup if available.
if BACKUP.exists():
    full = pd.read_csv(BACKUP, encoding="utf-8", low_memory=False)
else:
    full = pd.read_csv(AUDIT, encoding="utf-8", low_memory=False)
    shutil.copy2(AUDIT, BACKUP)

subset = full.iloc[START:START + COUNT].copy()

print("Full audit rows:", len(full))
print("Selected rows:", len(subset))
print("Start index:", START, "=> row", START + 1)
print("End row:", START + COUNT)

if len(subset) == 0:
    raise RuntimeError("No rows selected. Check START and COUNT.")

print("Start:", subset.iloc[0].get("repair_record_id", ""), subset.iloc[0].get("workflow_id", ""))
print("End:", subset.iloc[-1].get("repair_record_id", ""), subset.iloc[-1].get("workflow_id", ""))

try:
    subset.to_csv(AUDIT, index=False, encoding="utf-8")
    print("Temporary audit replaced with selected range only.")

    commands = [
        ["python", "-u", "scripts\\bookstore_strict_inplace_runtime_repair_v1.py", str(COUNT)],
        ["python", "-u", "scripts\\bookstore_strict_inplace_runtime_repair_v2_from_v1.py", str(COUNT)],
        ["python", "-u", "scripts\\bookstore_strict_inplace_runtime_repair_v3_from_v2.py", str(COUNT)],
        ["python", "-u", "scripts\\bookstore_strict_inplace_runtime_repair_v4_from_v3.py", str(COUNT)],
        ["python", "-u", "scripts\\bookstore_strict_inplace_runtime_repair_v5_from_v4.py", str(COUNT)],
        ["python", "-u", "scripts\\bookstore_strict_inplace_runtime_repair_v6_from_v5.py", str(COUNT)],
        ["python", "-u", "scripts\\bookstore_strict_inplace_runtime_repair_v7_from_v6.py", str(COUNT)],
        ["python", "-u", "scripts\\bookstore_strict_inplace_runtime_repair_v8_from_v7.py", str(COUNT)],
        ["python", "-u", "scripts\\bookstore_strict_inplace_runtime_repair_v9_from_v8.py", str(COUNT)],
    ]

    for cmd in commands:
        print("\nRunning:", " ".join(cmd), flush=True)
        p = subprocess.run(cmd, cwd=str(ROOT), env=env)
        if p.returncode != 0:
            raise RuntimeError("Command failed: " + " ".join(cmd))

    src = ROOT / "csv_dataset" / "objective1_bookstore_strict_inplace_runtime_repair_v9_results.csv"
    dst = ROOT / "csv_dataset" / f"objective1_bookstore_strict_inplace_runtime_repair_v9_rows{START+1}_{START+COUNT}.csv"

    if src.exists():
        shutil.copy2(src, dst)
        print("\nSaved range result:", dst)

finally:
    shutil.copy2(BACKUP, AUDIT)
    print("\nFull audit restored.")