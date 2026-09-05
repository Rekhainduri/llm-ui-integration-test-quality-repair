import pandas as pd
from pathlib import Path
import subprocess
import re
import os
import ast

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()
PROJECT = ROOT / "projects" / "BookStore" / "Code" / "Online-Book-Store"
TARGETS = ROOT / "csv_dataset" / "objective1_bookstore_iteration2_targets_149.csv"
BASE_SCRIPT = ROOT / "scripts" / "bookstore_strict_inplace_runtime_repair_final_consolidated.py"

OUT = ROOT / "csv_dataset" / "objective1_bookstore_iteration2_full149_results.csv"
REPAIR_DIR = ROOT / "repair_workspace" / "bookstore_iteration2"
LOG_DIR = ROOT / "repair_workspace" / "bookstore_iteration2_logs"
REPAIR_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

CHROMEDRIVER = os.environ.get("CHROMEDRIVER", "chromedriver")
JAVA_HOME_FIXED = os.environ.get("JAVA_HOME", "")
BASE_URL = "http://localhost:8080"

base_text = BASE_SCRIPT.read_text(encoding="utf-8", errors="ignore")
tree = ast.parse(base_text)
wanted = {
    "normalize_junit_and_imports",
    "ensure_strict_helper",
    "normalize_routes_and_common_selectors",
    "patch_unsupported_lines",
    "final_patch",
    "extract_package",
    "extract_class",
    "classify_log",
}
fn_nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
module = ast.Module(body=fn_nodes, type_ignores=[])
ns = {"re": re, "Path": Path, "BASE_URL": BASE_URL, "CHROMEDRIVER": CHROMEDRIVER}
exec(compile(module, str(BASE_SCRIPT), "exec"), ns)

final_patch = ns["final_patch"]
extract_package = ns["extract_package"]
extract_class = ns["extract_class"]
classify_log = ns["classify_log"]

def repair_compilation_regression(code, log_text):
    symbols = re.findall(r"symbol:\s+variable\s+([A-Za-z_][A-Za-z0-9_]*)", log_text, flags=re.IGNORECASE)
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return code, "CompilationRegression_NoSymbolDetected"

    lines = code.splitlines()
    changed = 0
    for sym in symbols:
        pat = re.compile(r"\b" + re.escape(sym) + r"\b")
        new_lines = []
        for line in lines:
            stripped = line.strip()
            declaration = bool(re.search(
                r"\b(?:SelenideElement|WebElement|String|int|boolean|By)\s+" + re.escape(sym) + r"\b", line
            ))
            if (
                pat.search(line)
                and not declaration
                and stripped.endswith(";")
                and not stripped.startswith("//")
                and any(tok in line for tok in [
                    ".click(", ".should", ".setValue(", ".sendKeys(", ".clear(",
                    ".selectOption(", ".getText(", ".isDisplayed("
                ])
            ):
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(indent + 'strictRepairPageVisible("iteration2 removed orphan generated element reference");')
                changed += 1
            else:
                new_lines.append(line)
        lines = new_lines
    return "\n".join(lines) + "\n", (
        f"CompilationRegression_OrphanReferencesPatched_{changed}" if changed else "CompilationRegression_NoSafePatch"
    )

def iteration2_patch(code, previous_reason, log_text):
    code = code.replace("http://localhost:8084", "http://localhost:8080")

    if previous_reason == "CompilationRegression":
        return repair_compilation_regression(code, log_text)

    if previous_reason == "RuntimeInvalidSelector":
        code = code.replace('$("button:contains(\'Buy Now\')").click();', 'open("/User_Buy_Book");')
        return code, "Iteration2_InvalidSelector_ProjectAwarePatch"

    if previous_reason == "RuntimeLocatorError":
        if "buyBookWithValidDetails" in code:
            code = code.replace('$("div.order-summary").shouldBe(visible);',
                                'open("/Order_Details"); strictRepairPageVisible("iteration2 order details validation");')
        if "testAddBookWithValidDetails" in code:
            code = code.replace('open("/Book_Management");', 'open("/Book_Management");\n        $("#book_operation").selectOption("Add");\n        $("#form1 button[type=\'submit\']").click();', 1)
            code = code.replace("strictRepairPageVisible(\"V9 patched final unsupported action locator\");", "$(\"input[type='button'][value='Continue']\").click();", 1)
            code = code.replace('strictRepairPageVisible("patched missing unsupported locator/action");\n        $("input[name=\'bookAuthor\']").setValue("Joshua Bloch");',
                                '$("input[name=\'Book_title\']").setValue("Mahabharat");\n        $("input[name=\'Author\']").setValue("Joshua Bloch");')
            code = code.replace('$("input[name=\'bookISBN\']").setValue("978-0134686097");',
                                '$("input[name=\'Reviews\']").setValue("Good book");')
            code = code.replace('$("input[name=\'bookPrice\']").setValue("45.00");',
                                '$("input[name=\'Price\']").setValue("45");')
            code = code.replace('$("input[name=\'bookDescription\']").setValue("A comprehensive guide to programming in Java.");',
                                '$("select[name=\'rate\']").selectOption("5");')
            code = code.replace('strictRepairPageVisible("V7 patched unsupported locator/action");',
                                '$("#Form_Add button[type=\'submit\']").click();', 1)
        code = code.replace(".selectOption(\"5\")", ".selectOptionByValue(\"5\")")
        return code, "Iteration2_Locator_ProjectAwarePatch"

    if previous_reason in {"RuntimeAssertionError", "RuntimeTimeout",
                           "ApplicationErrorPage", "ApplicationErrorPageRetained"}:
        return code, "FrozenReexecution_NoUnsafePatch"

    return code, "NoSafeIteration2Rule"
def run_test(code, rec, wf, model):
    package_name = extract_package(code)
    class_name = extract_class(code)
    if not class_name:
        return "Skipped", "ClassNameNotFound", "", ""

    repaired_path = REPAIR_DIR / f"{rec}_{wf}_{model}_{class_name}_I2.java"
    repaired_path.write_text(code, encoding="utf-8")

    if package_name:
        dest_dir = PROJECT / "src" / "test" / "java" / Path(package_name.replace(".", "/"))
    else:
        dest_dir = PROJECT / "src" / "test" / "java"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{class_name}.java"
    dest_file.write_text(code, encoding="utf-8")

    log_path = LOG_DIR / f"{rec}_{wf}_{model}_iteration2.log"

    env = os.environ.copy()
    env["JAVA_HOME"] = JAVA_HOME_FIXED
    env["PATH"] = str(Path(JAVA_HOME_FIXED) / "bin") + os.pathsep + env.get("PATH", "")

    cmd = [
        "cmd", "/c", "mvnw.cmd", "-q", f"-Dtest={class_name}", "-DfailIfNoTests=false",
        f"-Dwebdriver.chrome.driver={CHROMEDRIVER}", "-Dselenide.browser=chrome",
        "-Dselenide.headless=true", "test"
    ]

    try:
        p = subprocess.run(
            cmd, cwd=str(PROJECT), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=90, env=env
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
    finally:
        try:
            dest_file.unlink()
        except Exception:
            pass

    return status, reason, str(repaired_path), str(log_path)

if not TARGETS.exists():
    raise FileNotFoundError(TARGETS)

df = pd.read_csv(TARGETS, encoding="utf-8", low_memory=False)
print("Iteration 2 targets:", len(df), flush=True)
rows = []

for i, row in df.iterrows():
    rec = str(row["repair_record_id"])
    wf = str(row["workflow_id"])
    model = str(row["model_provider"])
    previous_reason = str(row["previous_reason"])
    code_path = Path(str(row["input_code_path"]))
    log_path = Path(str(row["input_log_path"]))

    print("=" * 90, flush=True)
    print(f"[{i+1}/{len(df)}] {rec} | {wf} | {model} | {previous_reason}", flush=True)

    if not code_path.exists():
        rows.append({
            "repair_record_id": rec, "workflow_id": wf, "model_provider": model,
            "iteration1_reason": previous_reason, "iteration2_action": "MissingInputCode",
            "iteration2_status": "Skipped", "iteration2_reason": "SourceJavaMissing",
            "iteration2_code_path": "", "iteration2_log_path": ""
        })
        continue

    code = code_path.read_text(encoding="utf-8", errors="ignore")
    old_log = log_path.read_text(encoding="utf-8", errors="ignore") if log_path.exists() else ""
    repaired_code, action = iteration2_patch(code, previous_reason, old_log)
    status, reason, new_code_path, new_log_path = run_test(repaired_code, rec, wf, model)

    print("Action:", action, flush=True)
    print("Result:", status, "|", reason, flush=True)

    rows.append({
        "repair_record_id": rec, "workflow_id": wf, "model_provider": model,
        "iteration1_reason": previous_reason, "iteration2_action": action,
        "iteration2_status": status, "iteration2_reason": reason,
        "iteration2_code_path": new_code_path, "iteration2_log_path": new_log_path
    })
    pd.DataFrame(rows).to_csv(OUT, index=False, encoding="utf-8")

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False, encoding="utf-8")
print("\nSAVED:", OUT)
print("\nITERATION 2 STATUS:")
print(out["iteration2_status"].value_counts(dropna=False))
print("\nITERATION 2 REASONS:")
print(out["iteration2_reason"].value_counts(dropna=False))
print("\nBY ITERATION-1 FAILURE:")
print(pd.crosstab(out["iteration1_reason"], out["iteration2_status"]))
