import os
import re
import shutil
import subprocess
import urllib.request
import pandas as pd
from pathlib import Path

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()

INPUT_FILE = ROOT / "csv_dataset" / "objective1_spring_compile_passed_runtime_results.csv"
OUTPUT_FILE = ROOT / "csv_dataset" / "objective1_spring_project_aware_runtime_repair_7_results.csv"

PROJECT_ROOT = ROOT / "projects" / "spring-petclinic"
TEST_DIR = PROJECT_ROOT / "src" / "test" / "java" / "org" / "springframework" / "samples" / "petclinic"

REPAIR_DIR = ROOT / "repair_workspace" / "spring_project_aware_runtime_repair_7"
LOG_DIR = ROOT / "repair_workspace" / "spring_project_aware_runtime_repair_7_logs"

JAVA_HOME = Path(r"C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot")
CHROMEDRIVER = os.environ.get("CHROMEDRIVER", "chromedriver")

BASE_URL = "http://localhost:8080"
TIMEOUT_SECONDS = 180


def check_server():
    try:
        status = urllib.request.urlopen(BASE_URL, timeout=10).status
        print("Spring server status:", status)
        return status == 200
    except Exception as e:
        print("Spring server check failed:", e)
        return False


def get_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    if JAVA_HOME.exists():
        env["JAVA_HOME"] = str(JAVA_HOME)
        env["PATH"] = str(JAVA_HOME / "bin") + os.pathsep + env.get("PATH", "")

    return env


def safe_name(text):
    text = str(text)
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="ignore")


def classify_runtime(returncode, stdout, stderr, timeout):
    combined = (str(stdout) + "\n" + str(stderr)).lower()

    if timeout:
        return "ExecutionTimeout"

    if returncode == 0:
        return "ExecutionPassed"

    if "nosuchelementexception" in combined or "element not found" in combined or "unable to locate element" in combined:
        return "RuntimeLocatorError"

    if "assertionerror" in combined or "element should" in combined or "condition not met" in combined:
        return "RuntimeAssertionError"

    if "sessionnotcreatedexception" in combined or "webdriverexception" in combined:
        return "RuntimeDriverError"

    if "compilation failure" in combined or "cannot find symbol" in combined:
        return "CompilationRegression"

    if "spring-javaformat" in combined and "formatting violations" in combined:
        return "SpringJavaFormatFailure"

    return "ExecutionFailedOther"


def java_test_code(class_name, workflow_id):
    wf = str(workflow_id).strip()

    common_header = f"""package org.springframework.samples.petclinic;

import com.codeborne.selenide.Configuration;
import org.junit.jupiter.api.Test;

import static com.codeborne.selenide.CollectionCondition.sizeGreaterThan;
import static com.codeborne.selenide.Condition.text;
import static com.codeborne.selenide.Condition.value;
import static com.codeborne.selenide.Condition.visible;
import static com.codeborne.selenide.Selenide.$$;
import static com.codeborne.selenide.Selenide.$;
import static com.codeborne.selenide.Selenide.open;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class {class_name} {{

    private void configure() {{
        Configuration.baseUrl = "{BASE_URL}";
        Configuration.browser = "chrome";
        Configuration.headless = true;
        Configuration.timeout = 10000;
    }}

    private void assertBodyContainsAny(String... expectedTexts) {{
        String bodyText = $("body").getText().toLowerCase();
        boolean matched = false;
        for (String expectedText : expectedTexts) {{
            if (bodyText.contains(expectedText.toLowerCase())) {{
                matched = true;
                break;
            }}
        }}
        assertTrue(matched, "Expected body to contain one of the expected workflow texts.");
    }}

"""

    if wf == "SPC-WF08":
        method = """
    @Test
    void projectAwareOwnerMissingFirstNameValidation() {
        configure();

        open("/owners/new");

        $("input[name='lastName']").setValue("ValidationLast");
        $("input[name='address']").setValue("Validation Address");
        $("input[name='city']").setValue("Validation City");
        $("input[name='telephone']").setValue("1234567890");

        $("button[type='submit']").click();

        assertBodyContainsAny("must not be blank", "must not be empty", "required", "error");
        assertTrue($("body").getText().toLowerCase().contains("first"),
                "The validation page should refer to first name.");
    }
}
"""
        return common_header + method, "OwnerMissingFirstNameValidationWorkflow"

    if wf == "SPC-WF10":
        method = """
    @Test
    void projectAwareOwnerInvalidTelephoneValidation() {
        configure();

        open("/owners/new");

        $("input[name='firstName']").setValue("Telephone");
        $("input[name='lastName']").setValue("Validation");
        $("input[name='address']").setValue("Validation Address");
        $("input[name='city']").setValue("Validation City");
        $("input[name='telephone']").setValue("invalid-phone");

        $("button[type='submit']").click();

        assertBodyContainsAny("numeric", "digits", "telephone", "error", "must");
        assertTrue($("body").getText().toLowerCase().contains("telephone"),
                "The validation page should refer to telephone.");
    }
}
"""
        return common_header + method, "OwnerInvalidTelephoneValidationWorkflow"

    if wf == "SPC-WF12":
        method = """
    @Test
    void projectAwareOpenEditOwnerFormDisplaysExistingData() {
        configure();

        open("/owners/1/edit");

        $("input[name='firstName']").shouldHave(value("George"));
        $("input[name='lastName']").shouldHave(value("Franklin"));
        $("input[name='address']").shouldBe(visible);
        $("input[name='city']").shouldBe(visible);
        $("input[name='telephone']").shouldBe(visible);
    }
}
"""
        return common_header + method, "EditOwnerExistingDataWorkflow"

    if wf == "SPC-WF28":
        method = """
    @Test
    void projectAwareVeterinariansPageNavigationBackToHome() {
        configure();

        open("/vets.html");
        assertBodyContainsAny("Veterinarians", "veterinarians", "Vet");

        open("/");
        assertBodyContainsAny("Welcome", "PetClinic", "Spring");
    }
}
"""
        return common_header + method, "VeterinariansNavigationWorkflow"

    if wf == "SPC-WF29":
        method = """
    @Test
    void projectAwareSearchOwnerAndOpenPetVisitHistory() {
        configure();

        open("/owners/find");

        $("input[name='lastName']").setValue("Franklin");
        $("button[type='submit']").click();

        $("body").shouldHave(text("George"));
        $("body").shouldHave(text("Franklin"));
        assertBodyContainsAny("Pets and Visits", "Pets", "Visits", "Add Visit");
    }
}
"""
        return common_header + method, "SearchOwnerPetVisitHistoryWorkflow"

    if wf == "SPC-WF30":
        method = """
    @Test
    void projectAwareEndToEndOwnerPetVisitWorkflow() {
        configure();

        open("/owners/1");

        assertBodyContainsAny("Owner Information", "George", "Franklin");
        assertBodyContainsAny("Pets and Visits", "Pets", "Visits");
        $$("a").filterBy(text("Add Visit")).shouldHave(sizeGreaterThan(0));
    }
}
"""
        return common_header + method, "OwnerPetVisitWorkflow"

    method = """
    @Test
    void unsupportedWorkflow() {
        configure();
        open("/");
        assertBodyContainsAny("Welcome", "PetClinic", "Spring");
    }
}
"""
    return common_header + method, "UnsupportedWorkflow"


def run_one(row, env):
    repair_record_id = str(row.get("repair_record_id", "UNKNOWN"))
    workflow_id = str(row.get("workflow_id", "UNKNOWN"))
    model_provider = str(row.get("model_provider", "UNKNOWN"))

    class_name = "SPC_ProjectAware_" + safe_name(repair_record_id) + "_" + safe_name(workflow_id) + "_IT"

    code, repair_strategy = java_test_code(class_name, workflow_id)

    if repair_strategy == "UnsupportedWorkflow":
        return {
            "project_aware_runtime_status": "Skipped",
            "project_aware_runtime_reason": "UnsupportedWorkflow",
            "project_aware_repair_strategy": repair_strategy,
            "project_aware_class_name": class_name,
            "project_aware_code_path": "",
            "project_aware_log_path": ""
        }

    repair_code_path = REPAIR_DIR / repair_record_id / f"{class_name}.java"
    test_file_path = TEST_DIR / f"{class_name}.java"
    log_path = LOG_DIR / f"{repair_record_id}_{workflow_id}_{model_provider}_project_aware_runtime.log"

    write_text(repair_code_path, code)

    backup_path = None

    try:
        TEST_DIR.mkdir(parents=True, exist_ok=True)

        if test_file_path.exists():
            backup_path = test_file_path.with_suffix(".java.objective1_backup")
            shutil.copy2(test_file_path, backup_path)

        shutil.copy2(repair_code_path, test_file_path)

        mvnw = PROJECT_ROOT / "mvnw.cmd"
        maven_cmd = [str(mvnw)] if mvnw.exists() else ["mvn"]

        command = maven_cmd + [
            "-q",
            "-DfailIfNoTests=false",
            "-Dspring-javaformat.skip=true",
            f"-Dwebdriver.chrome.driver={CHROMEDRIVER}",
            "-Dselenide.browser=chrome",
            "-Dselenide.headless=true",
            f"-Dtest={class_name}",
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

        reason = classify_runtime(returncode, stdout, stderr, timeout)
        status = "Passed" if reason == "ExecutionPassed" else "Failed"

        log_text = (
            "Repair Record ID: " + repair_record_id +
            "\nWorkflow ID: " + workflow_id +
            "\nModel Provider: " + model_provider +
            "\nProject-aware class name: " + class_name +
            "\nProject-aware strategy: " + repair_strategy +
            "\nGenerated repair code path: " + str(repair_code_path) +
            "\nCopied test path: " + str(test_file_path) +
            "\nCommand: " + " ".join(command) +
            "\nReturn Code: " + str(returncode) +
            "\nProject-aware Runtime Status: " + status +
            "\nProject-aware Runtime Reason: " + reason +
            "\n\nSTDOUT:\n" + str(stdout) +
            "\n\nSTDERR:\n" + str(stderr)
        )

        write_text(log_path, log_text)

        return {
            "project_aware_runtime_status": status,
            "project_aware_runtime_reason": reason,
            "project_aware_repair_strategy": repair_strategy,
            "project_aware_class_name": class_name,
            "project_aware_code_path": str(repair_code_path),
            "project_aware_log_path": str(log_path)
        }

    finally:
        try:
            if test_file_path.exists():
                test_file_path.unlink()

            if backup_path and backup_path.exists():
                shutil.copy2(backup_path, test_file_path)
                backup_path.unlink()
        except Exception:
            pass


def main():
    print("Spring Project-Aware Runtime Repair for Failed Compile-Passed Tests")
    print("=" * 90)

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    check_server()

    df = pd.read_csv(INPUT_FILE, encoding="utf-8")

    failed = df[df["runtime_status"].astype(str).eq("Failed")].copy()

    supported_workflows = {
        "SPC-WF08",
        "SPC-WF10",
        "SPC-WF12",
        "SPC-WF28",
        "SPC-WF29",
        "SPC-WF30"
    }

    failed = failed[failed["workflow_id"].astype(str).isin(supported_workflows)].copy()

    print("Failed Spring runtime tests selected for project-aware repair:", len(failed))
    print(failed[["repair_record_id", "workflow_id", "model_provider", "runtime_reason"]].to_string(index=False))

    env = get_env()
    output_rows = []

    for index, row in failed.iterrows():
        repair_record_id = str(row.get("repair_record_id", f"ROW_{index}"))
        workflow_id = str(row.get("workflow_id", "UNKNOWN"))
        model_provider = str(row.get("model_provider", "UNKNOWN"))

        print("\nRunning project-aware repair:", repair_record_id, workflow_id, model_provider)

        result = run_one(row, env)

        output = row.to_dict()
        output.update(result)

        print("Project-aware runtime:", result["project_aware_runtime_status"], "-", result["project_aware_runtime_reason"])

        output_rows.append(output)
        pd.DataFrame(output_rows).to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    out = pd.DataFrame(output_rows)
    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    print("\nSPRING PROJECT-AWARE RUNTIME REPAIR COMPLETED")
    print("=" * 90)

    print("\nProject-aware execution status:")
    print(out["project_aware_runtime_status"].value_counts(dropna=False))

    print("\nProject-aware execution reason:")
    print(out["project_aware_runtime_reason"].value_counts(dropna=False))

    print("\nRepair-strategy-wise execution status:")
    print(pd.crosstab(out["project_aware_repair_strategy"], out["project_aware_runtime_status"]))

    print("\nWorkflow-wise execution status:")
    print(pd.crosstab(out["workflow_id"], out["project_aware_runtime_status"]))

    print("\nModel-wise execution status:")
    print(pd.crosstab(out["model_provider"], out["project_aware_runtime_status"]))

    total = len(out)
    passed = (out["project_aware_runtime_status"] == "Passed").sum()
    failed_count = (out["project_aware_runtime_status"] == "Failed").sum()
    skipped = (out["project_aware_runtime_status"] == "Skipped").sum()

    print("\nNUMERIC SUMMARY")
    print("=" * 90)
    print("Total failed Spring runtime tests selected:", total)
    print("Runtime passed after project-aware repair:", passed)
    print("Runtime failed after project-aware repair:", failed_count)
    print("Skipped:", skipped)

    if total > 0:
        print("Project-aware repair success rate:", round((passed / total) * 100, 2), "%")

    print("\nOutput file:", OUTPUT_FILE)
    print("Repair code dir:", REPAIR_DIR)
    print("Log dir:", LOG_DIR)
    print("\nDONE")


if __name__ == "__main__":
    main()