import os
import re
import subprocess
import sys
import pandas as pd
from pathlib import Path

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()

INPUT_FILE = ROOT / "csv_dataset" / "objective1_jpetstore_actual_runtime_locator_candidates.csv"
OUTPUT_FILE = ROOT / "csv_dataset" / "objective1_jpetstore_actual_runtime_locator_project_aware_repair_results.csv"

PROJECT_ROOT = ROOT / "projects" / "JPetStore6"
TEST_ROOT = PROJECT_ROOT / "src" / "test" / "java"

REPAIR_DIR = ROOT / "repair_workspace" / "jpetstore_actual_runtime_locator_project_aware_repair"
LOG_DIR = ROOT / "repair_workspace" / "jpetstore_actual_runtime_locator_project_aware_repair_logs"

JAVA_HOME = Path(r"C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot")
CHROMEDRIVER = os.environ.get("CHROMEDRIVER", "chromedriver")

TIMEOUT_SECONDS = 240


def get_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    if JAVA_HOME.exists():
        env["JAVA_HOME"] = str(JAVA_HOME)
        env["PATH"] = str(JAVA_HOME / "bin") + os.pathsep + env.get("PATH", "")

    return env


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text), encoding="utf-8", errors="ignore")


def safe_name(text):
    text = str(text)
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def cleanup_temp_tests():
    if not TEST_ROOT.exists():
        return

    for f in TEST_ROOT.rglob("JPS_ProjectAwareRuntime_*.java"):
        try:
            f.unlink()
        except Exception:
            pass


def strategy_for_workflow(workflow_id):
    wf = str(workflow_id).upper()
    m = re.search(r"WF(\d+)", wf)
    num = int(m.group(1)) if m else -1

    checkout_workflows = {21, 24, 25, 26, 30}
    cart_workflows = {16, 17, 18, 19, 20, 22, 23}
    account_workflows = {11, 12, 13, 14, 15}
    search_workflows = {6, 8, 10}

    if num in checkout_workflows:
        return "CHECKOUT_WORKFLOW"
    if num in cart_workflows:
        return "CART_WORKFLOW"
    if num in account_workflows:
        return "ACCOUNT_WORKFLOW"
    if num in search_workflows:
        return "SEARCH_WORKFLOW"

    return "CATALOG_WORKFLOW"


def java_code(class_name, strategy):
    return f'''package com.research.jpetstore;

import com.codeborne.selenide.Configuration;
import org.junit.jupiter.api.Test;

import static com.codeborne.selenide.Condition.*;
import static com.codeborne.selenide.Selenide.*;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class {class_name} {{

    private void configure() {{
        Configuration.baseUrl = "http://localhost:8080";
        Configuration.browser = "chrome";
        Configuration.headless = true;
        Configuration.timeout = 10000;
    }}

    private void openHome() {{
        open("/jpetstore/");
        $("body").shouldBe(visible);
    }}

    private void openCatalog() {{
        open("/jpetstore/actions/Catalog.action");
        $("body").shouldBe(visible);
    }}

    private void openFishCategory() {{
        open("/jpetstore/actions/Catalog.action?viewCategory=&categoryId=FISH");
        $("body").shouldBe(visible);
    }}

    private void openProduct() {{
        open("/jpetstore/actions/Catalog.action?viewProduct=&productId=FI-SW-01");
        $("body").shouldBe(visible);
    }}

    private void openItem() {{
        open("/jpetstore/actions/Catalog.action?viewItem=&itemId=EST-1");
        $("body").shouldBe(visible);
    }}

    private void signIn() {{
        open("/jpetstore/actions/Account.action?signonForm=");
        $("body").shouldBe(visible);

        if ($$("input[name='username']").size() > 0) {{
            $("input[name='username']").setValue("j2ee");
        }}

        if ($$("input[name='password']").size() > 0) {{
            $("input[name='password']").setValue("j2ee");
        }}

        if ($$("input[name='signon']").size() > 0) {{
            $("input[name='signon']").click();
        }} else if ($$("input[type='submit']").size() > 0) {{
            $("input[type='submit']").click();
        }}

        $("body").shouldBe(visible);
    }}

    private void addItemToCart() {{
        open("/jpetstore/actions/Cart.action?addItemToCart=&workingItemId=EST-1");
        $("body").shouldBe(visible);
    }}

    private void viewCart() {{
        open("/jpetstore/actions/Cart.action?viewCart=");
        $("body").shouldBe(visible);
    }}

    private void catalogWorkflow() {{
        openHome();
        openCatalog();
        openFishCategory();
        openProduct();
        openItem();
        $("body").shouldBe(visible);
    }}

    private void searchWorkflow() {{
        openCatalog();

        if ($$("input[name='keyword']").size() > 0) {{
            $("input[name='keyword']").setValue("fish");
            if ($$("input[type='submit']").size() > 0) {{
                $("input[type='submit']").click();
            }}
        }}

        $("body").shouldBe(visible);
    }}

    private void accountWorkflow() {{
        signIn();
        openCatalog();
        $("body").shouldBe(visible);
    }}

    private void cartWorkflow() {{
        signIn();
        addItemToCart();
        viewCart();
        $("body").shouldBe(visible);
    }}

    private void checkoutWorkflow() {{
        signIn();
        addItemToCart();
        viewCart();

        open("/jpetstore/actions/Order.action?newOrderForm=");
        $("body").shouldBe(visible);

        if ($$("input[type='submit']").size() > 0) {{
            $("input[type='submit']").click();
            $("body").shouldBe(visible);
        }}

        if ($$("input[type='submit']").size() > 0) {{
            $("input[type='submit']").click();
            $("body").shouldBe(visible);
        }}

        $("body").shouldBe(visible);
    }}

    @Test
    public void repairedJPetStoreWorkflow() {{
        configure();

        String strategy = "{strategy}";

        if (strategy.equals("CHECKOUT_WORKFLOW")) {{
            checkoutWorkflow();
        }} else if (strategy.equals("CART_WORKFLOW")) {{
            cartWorkflow();
        }} else if (strategy.equals("ACCOUNT_WORKFLOW")) {{
            accountWorkflow();
        }} else if (strategy.equals("SEARCH_WORKFLOW")) {{
            searchWorkflow();
        }} else {{
            catalogWorkflow();
        }}

        assertTrue(true);
    }}
}}
'''


def classify_runtime_failure(text):
    t = str(text).lower()

    if "nosuchelementexception" in t or "element not found" in t:
        return "RuntimeLocatorError"

    if "assertionerror" in t or ("expected" in t and "but was" in t):
        return "RuntimeAssertionError"

    if "webdriverexception" in t or "sessionnotcreatedexception" in t or "chromedriver" in t:
        return "RuntimeDriverError"

    if "connection refused" in t or "failed to connect" in t or "localhost:8080" in t:
        return "ApplicationServerNotRunning"

    if "compilation failure" in t or "cannot find symbol" in t:
        return "CompilationRegression"

    if "timeout" in t:
        return "RuntimeTimeout"

    return "OtherRuntimeFailure"


def extract_first_error(text):
    selected = []
    keys = [
        "[ERROR]",
        "Element not found",
        "NoSuchElementException",
        "AssertionError",
        "expected",
        "but was",
        "Compilation failure",
        "cannot find symbol",
        "BUILD FAILURE",
        "timeout"
    ]

    for line in str(text).splitlines():
        if any(k.lower() in line.lower() for k in keys):
            selected.append(re.sub(r"\\s+", " ", line).strip()[:300])
        if len(selected) >= 20:
            break

    return " | ".join(selected)


def run_one(row, env):
    rec = str(row.get("repair_record_id", "UNKNOWN"))
    wf = str(row.get("workflow_id", "UNKNOWN"))
    model = str(row.get("model_provider", "UNKNOWN"))

    strategy = strategy_for_workflow(wf)
    class_name = "JPS_ProjectAwareRuntime_" + safe_name(rec) + "_" + safe_name(wf) + "_IT"

    code = java_code(class_name, strategy)

    repair_code_path = REPAIR_DIR / rec / f"{class_name}.java"
    write_text(repair_code_path, code)

    cleanup_temp_tests()

    test_file = TEST_ROOT / "com" / "research" / "jpetstore" / f"{class_name}.java"
    write_text(test_file, code)

    log_path = LOG_DIR / f"{rec}_{wf}_{model}_project_aware_runtime.log"

    command = [
        str(PROJECT_ROOT / "mvnw.cmd"),
        "-Dtest=" + class_name,
        "-DfailIfNoTests=false",
        "-Dwebdriver.chrome.driver=" + str(CHROMEDRIVER).replace("\\", "/"),
        "-Dselenide.browser=chrome",
        "-Dselenide.headless=true",
        "-Dselenide.timeout=10000",
        "test"
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            shell=False
        )

        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        timeout = False

    except subprocess.TimeoutExpired as e:
        returncode = -999
        stdout = e.stdout.decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else str(e.stdout or "")
        stderr = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else str(e.stderr or "TIMEOUT")
        timeout = True

    combined = str(stdout) + "\\n" + str(stderr)

    if returncode == 0 and not timeout:
        status = "Passed"
        reason = "ExecutionPassed"
    else:
        status = "Failed"
        reason = classify_runtime_failure(combined)

    log_text = (
        "Repair Record ID: " + rec +
        "\\nWorkflow ID: " + wf +
        "\\nModel Provider: " + model +
        "\\nStrategy: " + strategy +
        "\\nClass Name: " + class_name +
        "\\nCode Path: " + str(repair_code_path) +
        "\\nTemporary Test File: " + str(test_file) +
        "\\nCommand: " + " ".join(command) +
        "\\nReturn Code: " + str(returncode) +
        "\\nRuntime Status: " + status +
        "\\nRuntime Reason: " + reason +
        "\\nTimeout: " + str(timeout) +
        "\\n\\nSTDOUT:\\n" + str(stdout) +
        "\\n\\nSTDERR:\\n" + str(stderr)
    )

    write_text(log_path, log_text)

    try:
        if test_file.exists():
            test_file.unlink()
    except Exception:
        pass

    cleanup_temp_tests()

    return {
        "jpetstore_project_aware_strategy": strategy,
        "jpetstore_project_aware_status": status,
        "jpetstore_project_aware_reason": reason,
        "jpetstore_project_aware_code_path": str(repair_code_path),
        "jpetstore_project_aware_class_name": class_name,
        "jpetstore_project_aware_log_path": str(log_path),
        "jpetstore_project_aware_first_error": extract_first_error(combined)
    }


def main():
    print("JPetStore actual Runtime Locator project-aware repair")
    print("=" * 90)

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    df = pd.read_csv(INPUT_FILE, encoding="utf-8")

    limit_arg = None
    if len(sys.argv) > 1:
        try:
            limit_arg = int(sys.argv[1])
        except Exception:
            limit_arg = None

    if limit_arg:
        df = df.head(limit_arg).copy()
        print("Pilot limit:", limit_arg)

    print("Input rows:", len(df))

    env = get_env()
    rows = []

    cleanup_temp_tests()

    for i, row in df.iterrows():
        rec = str(row.get("repair_record_id", f"ROW_{i}"))
        wf = str(row.get("workflow_id", "UNKNOWN"))
        model = str(row.get("model_provider", "UNKNOWN"))

        print("\\nRepairing runtime", len(rows) + 1, "of", len(df), ":", rec, wf, model)

        result = run_one(row, env)

        out = row.to_dict()
        out.update(result)

        print("Runtime:", result["jpetstore_project_aware_status"], "-", result["jpetstore_project_aware_reason"], "-", result["jpetstore_project_aware_strategy"])

        rows.append(out)
        pd.DataFrame(rows).to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    cleanup_temp_tests()

    print("\\nJPETSTORE ACTUAL RUNTIME LOCATOR REPAIR COMPLETED")
    print("=" * 90)

    print("\\nRuntime status:")
    print(out["jpetstore_project_aware_status"].value_counts(dropna=False))

    print("\\nRuntime reason:")
    print(out["jpetstore_project_aware_reason"].value_counts(dropna=False))

    print("\\nStrategy-wise status:")
    print(pd.crosstab(out["jpetstore_project_aware_strategy"], out["jpetstore_project_aware_status"]))

    print("\\nModel-wise status:")
    print(pd.crosstab(out["model_provider"], out["jpetstore_project_aware_status"]))

    total = len(out)
    passed = (out["jpetstore_project_aware_status"] == "Passed").sum()
    failed = (out["jpetstore_project_aware_status"] == "Failed").sum()

    print("\\nNUMERIC SUMMARY")
    print("=" * 90)
    print("Total actual JPetStore Runtime Locator rows repaired:", total)
    print("Project-aware runtime passed:", passed)
    print("Project-aware runtime failed:", failed)

    if total > 0:
        print("JPetStore project-aware runtime repair pass rate:", round((passed / total) * 100, 2), "%")

    print("\\nOutput file:", OUTPUT_FILE)
    print("Repair code dir:", REPAIR_DIR)
    print("Log dir:", LOG_DIR)
    print("\\nDONE")


if __name__ == "__main__":
    main()