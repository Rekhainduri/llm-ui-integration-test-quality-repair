import os
import re
import shutil
import subprocess
import pandas as pd
from pathlib import Path

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()

INPUT_FILE = ROOT / "csv_dataset" / "objective1_bookstore_actual_runtime_locator_candidates.csv"
OUTPUT_FILE = ROOT / "csv_dataset" / "objective1_bookstore_actual_runtime_locator_project_aware_repair_results.csv"

PROJECT_ROOT = ROOT / "projects" / "BookStore" / "Code" / "Online-Book-Store"

REPAIR_DIR = ROOT / "repair_workspace" / "bookstore_project_aware_workflow_repair_all107"
LOG_DIR = ROOT / "repair_workspace" / "bookstore_project_aware_workflow_repair_all107_logs"

JAVA_HOME = Path(r"C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot")
CHROMEDRIVER = os.environ.get("CHROMEDRIVER", "chromedriver")

TIMEOUT_SECONDS = 180


def get_environment():
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


def sanitize_java_identifier(text):
    text = re.sub(r"[^A-Za-z0-9_]", "_", str(text))
    if re.match(r"^[0-9]", text):
        text = "_" + text
    return text


def destination_for_test_file(class_name):
    return PROJECT_ROOT / "src" / "test" / "java" / "com" / "online" / "book" / "store" / f"{class_name}.java"


def backup_existing_file(path):
    if not path.exists():
        return None

    backup = path.with_suffix(path.suffix + ".objective1_workflow_all107_backup")
    counter = 1

    while backup.exists():
        backup = path.with_suffix(path.suffix + f".objective1_workflow_all107_backup_{counter}")
        counter += 1

    shutil.copy2(path, backup)
    return backup


def restore_or_cleanup(path, backup):
    try:
        if path.exists():
            path.unlink()

        if backup and backup.exists():
            shutil.copy2(backup, path)
            backup.unlink()
    except Exception:
        pass


def workflow_group(workflow_id):
    wf = str(workflow_id).strip().upper()
    wf = wf.replace("BS-", "").replace("BOOKSTORE-", "").replace("BKS-", "")

    # BookStore actual runtime-locator workflow mapping
    if wf in {"WF01", "WF02", "WF03"}:
        return "UserBookSearchWorkflow"

    if wf in {"WF04", "WF05", "WF06"}:
        return "UserRegistrationWorkflow"

    if wf in {"WF07", "WF08", "WF09", "WF10", "WF11", "WF12", "WF13", "WF14", "WF15"}:
        return "AdminBookManagementWorkflow"

    if wf in {"WF16", "WF17", "WF18", "WF19", "WF20", "WF21", "WF22"}:
        return "AdminUserDetailsWorkflow"

    if wf in {"WF23", "WF24", "WF25", "WF26"}:
        return "AdminOrderDetailsWorkflow"

    if wf in {"WF27", "WF28", "WF29", "WF30"}:
        return "BookManagementOperationWorkflow"

    return "UnsupportedWorkflow"


def get_workflow_spec(workflow_id):
    wf = str(workflow_id).strip().upper()
    # Actual runtime-locator dataset uses BS-WF01 style IDs.
    # Original BookStore repair script expects WF01 style IDs.
    wf = wf.replace("BS-", "").replace("BOOKSTORE-", "").replace("BKS-", "")

    specs = {
        "BS-WF07": {
            "routes": ["/User", "/Login"],
            "terms": ["Registration", "Login", "New User", "Signup", "Online Book Store"]
        },
        "BS-WF11": {
            "routes": ["/User_Buy_Book", "/User_Books", "/User_Book_Details"],
            "terms": ["Search Book", "Buy Book", "Choose Book Operation", "Online Book Store", "User Logout"]
        },
        "BS-WF22": {
            "routes": ["/Book_Management", "/Book_Details", "/Admin_Home", "/"],
            "terms": ["Book Management", "Choose Book Operation", "Add", "Delete", "Admin Login Sucessfully"]
        },
        "BS-WF23": {
            "routes": ["/Book_Management", "/Book_Details", "/Admin_Home", "/"],
            "terms": ["Book Management", "Book Details", "Choose Book Operation", "Admin Login Sucessfully"]
        },
        "BS-WF24": {
            "routes": ["/Book_Details", "/Book_Management", "/Admin_Home", "/"],
            "terms": ["Book Details", "Book Management", "Admin Login Sucessfully"]
        },
        "BS-WF25": {
            "routes": ["/Book_Management", "/Book_Details", "/Admin_Home", "/"],
            "terms": ["Book Management", "Add", "Choose Book Operation", "Admin Login Sucessfully"]
        },
        "BS-WF26": {
            "routes": ["/Book_Management", "/Book_Details", "/Admin_Home", "/"],
            "terms": ["Book Management", "Delete", "Choose Book Operation", "Admin Login Sucessfully"]
        },
        "BS-WF27": {
            "routes": ["/Book_Management", "/Book_Details", "/Admin_Home", "/"],
            "terms": ["Book Management", "Delete", "Choose Book Operation", "Admin Login Sucessfully"]
        },
        "BS-WF28": {
            "routes": ["/Book_Details", "/Book_Management", "/Admin_Home", "/"],
            "terms": ["Book Details", "Book Management", "Admin Login Sucessfully"]
        },
        "BS-WF29": {
            "routes": ["/User_Details", "/Admin_Home", "/Book_Management", "/"],
            "terms": ["User Details", "Admin Login Sucessfully", "Book Management"]
        },
        "BS-WF30": {
            "routes": ["/Order_Details", "/Admin_Home", "/"],
            "terms": ["Order Details", "Admin Login Sucessfully", "Online Book Store"]
        },
    }

    return specs.get(wf, None)


def java_array(items):
    return ", ".join([f'"{x}"' for x in items])


def generate_java_test(class_name, workflow_id, repair_record_id, model_provider):
    group = workflow_group(workflow_id)
    spec = get_workflow_spec(workflow_id)

    if spec is None:
        return "", group

    routes = java_array(spec["routes"])
    terms = java_array(spec["terms"])

    code = f'''package com.online.book.store;

import org.junit.Test;
import com.codeborne.selenide.Configuration;

import static com.codeborne.selenide.Selenide.*;
import static org.junit.Assert.*;

public class {class_name} {{

    @Test
    public void validateProjectAwareWorkflowReconstruction() {{
        configureBookStoreRuntime();

        String workflowId = "{workflow_id}";
        String repairRecordId = "{repair_record_id}";
        String modelProvider = "{model_provider}";

        String[] routes = new String[] {{{routes}}};
        String[] expectedTerms = new String[] {{{terms}}};

        openFirstValidRoute(routes, expectedTerms, workflowId);

        String bodyText = bodyText();

        assertTrue(
            containsAny(bodyText, expectedTerms),
            "Expected mapped BookStore workflow terms for " + workflowId + ", but actual body was: " + bodyText
        );
    }}

    private void configureBookStoreRuntime() {{
        Configuration.baseUrl = "http://localhost:8084";
        Configuration.browser = "chrome";
        Configuration.headless = true;
        Configuration.timeout = 10000;
    }}

    private void openFirstValidRoute(String[] routes, String[] expectedTerms, String workflowId) {{
        StringBuilder attempts = new StringBuilder();

        for (String route : routes) {{
            try {{
                open(route);
                sleep(500);

                String bodyText = bodyText();

                attempts.append("\\nRoute: ")
                        .append(route)
                        .append("\\nBody: ")
                        .append(shortText(bodyText));

                if (
                    !bodyText.contains("Whitelabel Error Page")
                    && !bodyText.contains("Internal Server Error")
                    && containsAny(bodyText, expectedTerms)
                ) {{
                    return;
                }}
            }}
            catch (Throwable error) {{
                attempts.append("\\nRoute: ")
                        .append(route)
                        .append("\\nError: ")
                        .append(error.getMessage());
            }}
        }}

        fail("No valid mapped BookStore route found for workflow " + workflowId + ". Attempts: " + attempts);
    }}

    private boolean containsAny(String text, String[] expectedTerms) {{
        if (text == null) {{
            return false;
        }}

        for (String term : expectedTerms) {{
            if (text.contains(term)) {{
                return true;
            }}
        }}

        return false;
    }}

    private String bodyText() {{
        try {{
            if ($$("body").size() == 0) {{
                return "";
            }}

            return $("body").text();
        }}
        catch (Throwable error) {{
            return "";
        }}
    }}

    private String shortText(String text) {{
        if (text == null) {{
            return "";
        }}

        text = text.replaceAll("\\\\s+", " ").trim();

        if (text.length() > 300) {{
            return text.substring(0, 300);
        }}

        return text;
    }}
}}
'''

    return code, group


def classify_runtime_result(returncode, stdout, stderr, timeout):
    combined = (str(stdout) + "\n" + str(stderr)).lower()

    if timeout:
        return "ExecutionTimeout"

    if returncode == 0:
        return "ExecutionPassed"

    if "unable to locate the chromedriver" in combined:
        return "ChromeDriverPathError"

    if "sessionnotcreatedexception" in combined or "webdriverexception" in combined:
        return "RuntimeDriverError"

    if "nosuchelementexception" in combined or "element not found" in combined:
        return "RuntimeLocatorError"

    if "assertionerror" in combined or "element should" in combined or "condition not met" in combined:
        return "RuntimeAssertionError"

    if "compilation failure" in combined or "compilation error" in combined or "cannot find symbol" in combined:
        return "CompilationRegression"

    return "ExecutionFailedOther"


def run_command(command, env):
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

        return completed.returncode, completed.stdout, completed.stderr, False

    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if error.stdout else ""
        stderr = error.stderr if error.stderr else "TIMEOUT"

        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")

        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")

        return -999, stdout, stderr, True

    except Exception as error:
        return -998, "", str(error), False


def execute_generated_test(row, generated_java_path, class_name, env):
    repair_record_id = str(row.get("repair_record_id", "UNKNOWN"))
    workflow_id = str(row.get("workflow_id", "UNKNOWN"))
    model_provider = str(row.get("model_provider", "UNKNOWN"))

    destination_path = destination_for_test_file(class_name)
    backup = None

    log_path = LOG_DIR / f"{repair_record_id}_{workflow_id}_{model_provider}_all107_workflow_repair.log"

    try:
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        backup = backup_existing_file(destination_path)
        shutil.copy2(generated_java_path, destination_path)

        mvnw = PROJECT_ROOT / "mvnw.cmd"
        maven_cmd = [str(mvnw)] if mvnw.exists() else ["mvn"]

        command = maven_cmd + [
            "-q",
            "-DfailIfNoTests=false",
            "-Dsurefire.failIfNoSpecifiedTests=false",
            f"-Dwebdriver.chrome.driver={CHROMEDRIVER}",
            "-Dselenide.browser=chrome",
            "-Dselenide.headless=true",
            f"-Dtest={class_name}",
            "test"
        ]

        returncode, stdout, stderr, timeout = run_command(command, env)

        reason = classify_runtime_result(returncode, stdout, stderr, timeout)
        status = "Passed" if reason == "ExecutionPassed" else "Failed"

        log_text = (
            "Repair Record ID: " + repair_record_id +
            "\nWorkflow ID: " + workflow_id +
            "\nModel Provider: " + model_provider +
            "\nGenerated workflow-repair Java path: " + str(generated_java_path) +
            "\nCopied test path: " + str(destination_path) +
            "\nCommand: " + " ".join(command) +
            "\nReturn Code: " + str(returncode) +
            "\nRuntime Status: " + status +
            "\nRuntime Reason: " + reason +
            "\n\nSTDOUT:\n" + str(stdout) +
            "\n\nSTDERR:\n" + str(stderr)
        )

        write_text(log_path, log_text)

        return status, reason, str(log_path)

    finally:
        restore_or_cleanup(destination_path, backup)


def main():
    print("BookStore project-aware workflow reconstruction validation on all107")
    print("=" * 90)

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    env = get_environment()

    df = pd.read_csv(INPUT_FILE, encoding="utf-8")

    # For actual Runtime / Locator Error rows, all rows are already runtime-failure candidates.
    # Therefore, do not filter using progressive_final_status.
    selected = df.copy()
    
    # Optional pilot limit: python script.py 20
    try:
        import sys
        if len(sys.argv) > 1:
            pilot_n = int(sys.argv[1])
            selected = selected.head(pilot_n).copy()
            print('Pilot limit:', pilot_n)
    except Exception as e:
        print('Pilot limit not applied:', e)

    print("Total progressive repair rows:", len(df))
    print("Compile-passed repaired rows selected:", len(selected))

    output_rows = []

    for index, row in selected.iterrows():
        repair_record_id = str(row.get("repair_record_id", f"ROW_{index}"))
        workflow_id = str(row.get("workflow_id", "UNKNOWN"))
        model_provider = str(row.get("model_provider", "UNKNOWN"))

        print(
            "\nValidating",
            len(output_rows) + 1,
            "of",
            len(selected),
            ":",
            repair_record_id,
            workflow_id,
            model_provider
        )

        group = workflow_group(workflow_id)

        output = row.to_dict()
        output["project_aware_repair_strategy"] = group

        if group == "UnsupportedWorkflow":
            output["project_aware_generated_java_path"] = ""
            output["project_aware_execution_status"] = "Skipped"
            output["project_aware_execution_reason"] = "UnsupportedWorkflow"
            output["project_aware_log_path"] = ""

            print("Project-aware runtime: Skipped - UnsupportedWorkflow")

            output_rows.append(output)
            pd.DataFrame(output_rows).to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
            continue

        class_name = (
            "BS_"
            + sanitize_java_identifier(workflow_id)
            + "_"
            + sanitize_java_identifier(model_provider)
            + "_"
            + sanitize_java_identifier(repair_record_id)
            + "_All107ProjectAwareWorkflowRepair_IT"
        )

        java_code, group = generate_java_test(
            class_name,
            workflow_id,
            repair_record_id,
            model_provider
        )

        generated_java_path = REPAIR_DIR / model_provider / repair_record_id / f"{class_name}.java"

        write_text(generated_java_path, java_code)

        status, reason, log_path = execute_generated_test(
            row,
            generated_java_path,
            class_name,
            env
        )

        output["project_aware_repair_strategy"] = group
        output["project_aware_generated_java_path"] = str(generated_java_path)
        output["project_aware_execution_status"] = status
        output["project_aware_execution_reason"] = reason
        output["project_aware_log_path"] = log_path

        print("Project-aware runtime:", status, "-", reason)

        output_rows.append(output)
        pd.DataFrame(output_rows).to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    out = pd.DataFrame(output_rows)
    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    print("\nBOOKSTORE ALL107 PROJECT-AWARE WORKFLOW VALIDATION COMPLETED")
    print("=" * 90)

    print("\nProject-aware execution status:")
    print(out["project_aware_execution_status"].value_counts(dropna=False))

    print("\nProject-aware execution reason:")
    print(out["project_aware_execution_reason"].value_counts(dropna=False))

    print("\nWorkflow-wise project-aware execution status:")
    print(pd.crosstab(out["workflow_id"], out["project_aware_execution_status"]))

    print("\nRepair-strategy-wise execution status:")
    print(pd.crosstab(out["project_aware_repair_strategy"], out["project_aware_execution_status"]))

    print("\nModel-wise project-aware execution status:")
    print(pd.crosstab(out["model_provider"], out["project_aware_execution_status"]))

    total = len(out)
    passed = (out["project_aware_execution_status"] == "Passed").sum()
    skipped = (out["project_aware_execution_status"] == "Skipped").sum()
    failed = (out["project_aware_execution_status"] == "Failed").sum()
    mapped = total - skipped

    print("\nNUMERIC SUMMARY")
    print("=" * 90)
    print("Total compile-repaired BookStore tests selected:", total)
    print("Mapped workflow tests:", mapped)
    print("Unsupported workflow tests:", skipped)
    print("Runtime passed after project-aware workflow validation:", passed)
    print("Runtime failed after project-aware workflow validation:", failed)
    print("Skipped:", skipped)

    if total > 0:
        print("Overall pass rate including unsupported/skipped:", round((passed / total) * 100, 2), "%")

    if mapped > 0:
        print("Mapped-workflow pass rate:", round((passed / mapped) * 100, 2), "%")

    print("\nIMPORTANT INTERPRETATION")
    print("=" * 90)
    print("This is project-aware workflow reconstruction/validation.")
    print("It should not be reported as line-by-line repair of the original generated test code.")
    print("Unsupported workflows are intentionally skipped.")

    print("\nDONE")


if __name__ == "__main__":
    main()
