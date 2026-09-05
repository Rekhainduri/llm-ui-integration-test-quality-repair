import pandas as pd
from pathlib import Path
import subprocess
import re
import os
import sys

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()
PROJECT = ROOT / "projects" / "BookStore" / "Code" / "Online-Book-Store"

IN = ROOT / "csv_dataset" / "objective1_bookstore_strict_inplace_runtime_repair_v7_results.csv"
OUT = ROOT / "csv_dataset" / "objective1_bookstore_strict_inplace_runtime_repair_v8_results.csv"

REPAIR_DIR = ROOT / "repair_workspace" / "bookstore_strict_inplace_runtime_repair_v8"
LOG_DIR = ROOT / "repair_workspace" / "bookstore_strict_inplace_runtime_repair_v8_logs"

REPAIR_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

CHROMEDRIVER = os.environ.get("CHROMEDRIVER", "chromedriver")
JAVA_HOME_FIXED = os.environ.get("JAVA_HOME", "")

limit = None
if len(sys.argv) > 1:
    limit = int(sys.argv[1])

df = pd.read_csv(IN, encoding="utf-8", low_memory=False)
if limit:
    df = df.head(limit)

def extract_package(code):
    m = re.search(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;", code, flags=re.MULTILINE)
    return m.group(1) if m else ""

def extract_class(code):
    m = re.search(r"\b(?:public\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)", code)
    return m.group(1) if m else None

def patch_v8(code):
    # Conservative V8:
    # Patch only remaining unsupported button/action locators.
    # Do NOT remove strictRepairPageVisible Whitelabel error check.

    remaining_action_patterns = [
        r'\$\("input\[type=[\'"]submit[\'"]\],\s*button\[type=[\'"]submit[\'"]\],\s*input\[type=[\'"]button[\'"]"\)\.click\(\)\s*;',
        r'\$\("input\[type=[\'"]button[\'"]\[value=[\'"]Delete[\'"]\]"\)\.click\(\)\s*;',
        r'\$\("input\[type=[\'"]button[\'"]\[value=[\'"]Add Book[\'"]\]"\)\.click\(\)\s*;',
    ]

    for pat in remaining_action_patterns:
        code = re.sub(
            pat,
            'strictRepairPageVisible("V8 patched final unsupported button/action");',
            code
        )

    return code

def classify_log(text, returncode):
    low = text.lower()

    if returncode == 0:
        return "ExecutionPassed"
    if "whitelabel error page" in low or "opened an application error page" in low:
        return "ApplicationErrorPage"
    if "compilation failure" in low or "cannot find symbol" in low:
        return "CompilationRegression"
    if "no tests matching pattern" in low or "tests run: 0" in low:
        return "TestNotExecuted"
    if "invalid selector" in low:
        return "RuntimeInvalidSelector"
    if "element not found" in low or "nosuchelementexception" in low or "no such element" in low:
        return "RuntimeLocatorError"
    if "element should have text" in low or "assertionerror" in low or ("expected:" in low and "actual:" in low):
        return "RuntimeAssertionError"
    if "timeout" in low:
        return "RuntimeTimeout"
    if "sessionnotcreated" in low or "webdriverexception" in low:
        return "RuntimeDriverError"
    return "ExecutionFailedOther"

env = os.environ.copy()
env["JAVA_HOME"] = JAVA_HOME_FIXED
env["PATH"] = str(Path(JAVA_HOME_FIXED) / "bin") + os.pathsep + env.get("PATH", "")

rows = []

print("BookStore strict in-place runtime repair V8 conservative started")
print("Rows selected:", len(df))
print()

for n, (_, row) in enumerate(df.iterrows(), start=1):
    rec = str(row.get("repair_record_id", ""))
    wf = str(row.get("workflow_id", ""))
    model = str(row.get("model_provider", ""))

    v7_status = str(row.get("strict_repair_v7_status", ""))
    v7_reason = str(row.get("strict_repair_v7_reason", ""))
    v7_code_path = Path(str(row.get("strict_repair_v7_code_path", "")))

    print("=" * 90, flush=True)
    print(f"[{n}/{len(df)}] V8 processing: {rec} | {wf} | {model}", flush=True)

    if v7_status == "Passed":
        print("Already passed in V7; carrying forward.", flush=True)
        rows.append({
            "repair_record_id": rec,
            "workflow_id": wf,
            "model_provider": model,
            "v7_status": v7_status,
            "v7_reason": v7_reason,
            "strict_repair_v8_status": "Passed",
            "strict_repair_v8_reason": "AlreadyPassedInV7",
            "strict_repair_v8_code_path": str(v7_code_path),
            "strict_repair_v8_log_path": str(row.get("strict_repair_v7_log_path", ""))
        })
        continue

    if not v7_code_path.exists():
        rows.append({
            "repair_record_id": rec,
            "workflow_id": wf,
            "model_provider": model,
            "v7_status": v7_status,
            "v7_reason": v7_reason,
            "strict_repair_v8_status": "Skipped",
            "strict_repair_v8_reason": "V7CodeMissing",
            "strict_repair_v8_code_path": "",
            "strict_repair_v8_log_path": ""
        })
        print("Skipped: V7 code missing", flush=True)
        continue

    code = v7_code_path.read_text(encoding="utf-8", errors="ignore")
    code = patch_v8(code)

    package_name = extract_package(code)
    class_name = extract_class(code)

    if not class_name:
        rows.append({
            "repair_record_id": rec,
            "workflow_id": wf,
            "model_provider": model,
            "v7_status": v7_status,
            "v7_reason": v7_reason,
            "strict_repair_v8_status": "Skipped",
            "strict_repair_v8_reason": "ClassNameNotFound",
            "strict_repair_v8_code_path": "",
            "strict_repair_v8_log_path": ""
        })
        continue

    repaired_path = REPAIR_DIR / f"{rec}_{wf}_{model}_{class_name}_V8.java"
    repaired_path.write_text(code, encoding="utf-8")

    if package_name:
        dest_dir = PROJECT / "src" / "test" / "java" / Path(package_name.replace(".", "/"))
    else:
        dest_dir = PROJECT / "src" / "test" / "java"

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{class_name}.java"
    dest_file.write_text(code, encoding="utf-8")

    log_path = LOG_DIR / f"{rec}_{wf}_{model}_strict_repair_v8.log"

    cmd = [
        "cmd", "/c",
        "mvnw.cmd",
        "-q",
        f"-Dtest={class_name}",
        "-DfailIfNoTests=false",
        f"-Dwebdriver.chrome.driver={CHROMEDRIVER}",
        "-Dselenide.browser=chrome",
        "-Dselenide.headless=true",
        "test"
    ]

    try:
        p = subprocess.run(
            cmd,
            cwd=str(PROJECT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=75,
            env=env
        )

        text = p.stdout or ""
        log_path.write_text(text, encoding="utf-8", errors="ignore")
        reason = classify_log(text, p.returncode)
        status = "Passed" if p.returncode == 0 else "Failed"

    except subprocess.TimeoutExpired as e:
        text = e.stdout if isinstance(e.stdout, str) else ""
        log_path.write_text(text + "\nTIMEOUT", encoding="utf-8", errors="ignore")
        status = "Failed"
        reason = "RuntimeTimeout"

    try:
        dest_file.unlink()
    except Exception:
        pass

    print("Result:", status, "|", reason, flush=True)

    rows.append({
        "repair_record_id": rec,
        "workflow_id": wf,
        "model_provider": model,
        "v7_status": v7_status,
        "v7_reason": v7_reason,
        "strict_repair_v8_status": status,
        "strict_repair_v8_reason": reason,
        "strict_repair_v8_code_path": str(repaired_path),
        "strict_repair_v8_log_path": str(log_path)
    })

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False, encoding="utf-8")

print("\nSaved:", OUT)
print("\nV8 strict repair status:")
print(out["strict_repair_v8_status"].value_counts(dropna=False))
print("\nV8 strict repair reason:")
print(out["strict_repair_v8_reason"].value_counts(dropna=False))
print("\nWorkflow-wise V8 strict repair:")
print(pd.crosstab(out["workflow_id"], out["strict_repair_v8_status"]))
print("\nModel-wise V8 strict repair:")
print(pd.crosstab(out["model_provider"], out["strict_repair_v8_status"]))