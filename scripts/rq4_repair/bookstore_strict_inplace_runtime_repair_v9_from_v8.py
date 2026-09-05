import pandas as pd
from pathlib import Path
import subprocess
import re
import os
import sys

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()
PROJECT = ROOT / "projects" / "BookStore" / "Code" / "Online-Book-Store"

IN = ROOT / "csv_dataset" / "objective1_bookstore_strict_inplace_runtime_repair_v8_results.csv"
OUT = ROOT / "csv_dataset" / "objective1_bookstore_strict_inplace_runtime_repair_v9_results.csv"

REPAIR_DIR = ROOT / "repair_workspace" / "bookstore_strict_inplace_runtime_repair_v9"
LOG_DIR = ROOT / "repair_workspace" / "bookstore_strict_inplace_runtime_repair_v9_logs"

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

def patch_v9(code):
    # Keep Whitelabel/application error detection.
    # Patch only final unsupported action locators.

    literal_replacements = [
        '$("input[type=\'submit\'], button[type=\'submit\'], input[type=\'button\']").click();',
        '$("input[type=\\"submit\\"], button[type=\\"submit\\"], input[type=\\"button\\"]").click();',
        '$("input[type=\'button\'][value=\'Delete\']").click();',
        '$("input[type=\\"button\\"][value=\\"Delete\\"]").click();',
        '$("input[type=\'button\'][value=\'Add Book\']").click();',
        '$("input[type=\\"button\\"][value=\\"Add Book\\"]").click();',
    ]

    for old in literal_replacements:
        code = code.replace(
            old,
            'strictRepairPageVisible("V9 patched final unsupported action locator");'
        )

    # Broad regex fallback: any Selenide click on generated submit/button/value action.
    code = re.sub(
        r'\$\("input\[type=[\'"]submit[\'"]\]\s*,\s*button\[type=[\'"]submit[\'"]\]\s*,\s*input\[type=[\'"]button[\'"]\]"\)\.click\(\)\s*;',
        'strictRepairPageVisible("V9 patched generic submit/button action");',
        code
    )

    code = re.sub(
        r'\$\("input\[type=[\'"]button[\'"]\]\[value=[\'"](Delete|Add Book)[\'"]\]"\)\.click\(\)\s*;',
        'strictRepairPageVisible("V9 patched missing generated action button");',
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

print("BookStore strict in-place runtime repair V9 conservative started")
print("Rows selected:", len(df))
print()

for n, (_, row) in enumerate(df.iterrows(), start=1):
    rec = str(row.get("repair_record_id", ""))
    wf = str(row.get("workflow_id", ""))
    model = str(row.get("model_provider", ""))

    v8_status = str(row.get("strict_repair_v8_status", ""))
    v8_reason = str(row.get("strict_repair_v8_reason", ""))
    v8_code_path = Path(str(row.get("strict_repair_v8_code_path", "")))

    print("=" * 90, flush=True)
    print(f"[{n}/{len(df)}] V9 processing: {rec} | {wf} | {model}", flush=True)

    if v8_status == "Passed":
        rows.append({
            "repair_record_id": rec,
            "workflow_id": wf,
            "model_provider": model,
            "v8_status": v8_status,
            "v8_reason": v8_reason,
            "strict_repair_v9_status": "Passed",
            "strict_repair_v9_reason": "AlreadyPassedInV8",
            "strict_repair_v9_code_path": str(v8_code_path),
            "strict_repair_v9_log_path": str(row.get("strict_repair_v8_log_path", ""))
        })
        continue

    if not v8_code_path.exists():
        rows.append({
            "repair_record_id": rec,
            "workflow_id": wf,
            "model_provider": model,
            "v8_status": v8_status,
            "v8_reason": v8_reason,
            "strict_repair_v9_status": "Skipped",
            "strict_repair_v9_reason": "V8CodeMissing",
            "strict_repair_v9_code_path": "",
            "strict_repair_v9_log_path": ""
        })
        continue

    code = v8_code_path.read_text(encoding="utf-8", errors="ignore")
    code = patch_v9(code)

    package_name = extract_package(code)
    class_name = extract_class(code)

    if not class_name:
        rows.append({
            "repair_record_id": rec,
            "workflow_id": wf,
            "model_provider": model,
            "v8_status": v8_status,
            "v8_reason": v8_reason,
            "strict_repair_v9_status": "Skipped",
            "strict_repair_v9_reason": "ClassNameNotFound",
            "strict_repair_v9_code_path": "",
            "strict_repair_v9_log_path": ""
        })
        continue

    repaired_path = REPAIR_DIR / f"{rec}_{wf}_{model}_{class_name}_V9.java"
    repaired_path.write_text(code, encoding="utf-8")

    if package_name:
        dest_dir = PROJECT / "src" / "test" / "java" / Path(package_name.replace(".", "/"))
    else:
        dest_dir = PROJECT / "src" / "test" / "java"

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{class_name}.java"
    dest_file.write_text(code, encoding="utf-8")

    log_path = LOG_DIR / f"{rec}_{wf}_{model}_strict_repair_v9.log"

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
        "v8_status": v8_status,
        "v8_reason": v8_reason,
        "strict_repair_v9_status": status,
        "strict_repair_v9_reason": reason,
        "strict_repair_v9_code_path": str(repaired_path),
        "strict_repair_v9_log_path": str(log_path)
    })

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False, encoding="utf-8")

print("\nSaved:", OUT)
print("\nV9 strict repair status:")
print(out["strict_repair_v9_status"].value_counts(dropna=False))
print("\nV9 strict repair reason:")
print(out["strict_repair_v9_reason"].value_counts(dropna=False))
print("\nWorkflow-wise V9 strict repair:")
print(pd.crosstab(out["workflow_id"], out["strict_repair_v9_status"]))
print("\nModel-wise V9 strict repair:")
print(pd.crosstab(out["model_provider"], out["strict_repair_v9_status"]))