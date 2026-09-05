import os
import re
import shutil
import subprocess
import pandas as pd
from pathlib import Path

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()

INPUT_FILE = ROOT / "csv_dataset" / "objective1_spring_compilation_repair_results.csv"
OUTPUT_FILE = ROOT / "csv_dataset" / "objective1_spring_compilation_repair_remaining_85_results.csv"

PROJECT_ROOT = ROOT / "projects" / "spring-petclinic"
TEST_DIR = PROJECT_ROOT / "src" / "test" / "java" / "org" / "springframework" / "samples" / "petclinic"

REPAIR_DIR = ROOT / "repair_workspace" / "spring_compilation_repair_remaining_85"
LOG_DIR = ROOT / "repair_workspace" / "spring_compilation_repair_remaining_85_logs"

JAVA_HOME = Path(r"C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot")

TIMEOUT_SECONDS = 180


def get_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    if JAVA_HOME.exists():
        env["JAVA_HOME"] = str(JAVA_HOME)
        env["PATH"] = str(JAVA_HOME / "bin") + os.pathsep + env.get("PATH", "")

    return env


def read_text(path):
    return Path(str(path)).read_text(encoding="utf-8", errors="ignore")


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text), encoding="utf-8", errors="ignore")


def safe_name(text):
    text = str(text)
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def resolve_source_path(row):
    candidate_cols = [
        "final_repaired_code_path",
        "repaired_code_path",
        "generated_test_code_path",
        "original_code_path"
    ]

    for col in candidate_cols:
        value = str(row.get(col, "")).strip()
        if value and value.lower() != "nan" and Path(value).exists():
            return Path(value), col

    return None, ""


def extract_first_error(log_text):
    lines = str(log_text).splitlines()
    selected = []

    keys = [
        "[ERROR]",
        "cannot find symbol",
        "incompatible types",
        "method",
        "symbol:",
        "location:",
        "compilation failure",
        "package",
        "class",
        "interface expected"
    ]

    for line in lines:
        low = line.lower()
        if any(k.lower() in low for k in keys):
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                selected.append(line[:300])
        if len(selected) >= 20:
            break

    return " | ".join(selected)


def classify_compile_failure(log_text):
    text = str(log_text).lower()

    if "cannot find symbol" in text:
        return "CannotFindSymbol"

    if "incompatible types" in text:
        return "IncompatibleTypes"

    if "method" in text and "cannot be applied" in text:
        return "MethodArgumentMismatch"

    if "';' expected" in text:
        return "MissingSemicolon"

    if "spring-javaformat" in text and "formatting violations" in text:
        return "SpringJavaFormatFailure"

    if "compilation failure" in text:
        return "MavenTestCompileFailure"

    return "OtherCompilationFailure"


def remove_generated_test_leftovers():
    if not TEST_DIR.exists():
        return

    prefixes = [
        "SPC_CompileRepair_",
        "SPC_ProjectAware_",
        "SPCWF",
        "SPC_WF"
    ]

    for file in TEST_DIR.glob("*.java"):
        if any(file.name.startswith(prefix) for prefix in prefixes):
            try:
                file.unlink()
            except Exception:
                pass


def normalize_package_and_class(code, class_name):
    code = str(code)

    code = code.replace("\ufeff", "")

    code = re.sub(
        r"^\s*package\s+[^;]+;",
        "package org.springframework.samples.petclinic;",
        code,
        count=1,
        flags=re.MULTILINE
    )

    if "package org.springframework.samples.petclinic;" not in code:
        code = "package org.springframework.samples.petclinic;\n\n" + code

    code = re.sub(
        r"\bpublic\s+class\s+[A-Za-z0-9_]+",
        f"public class {class_name}",
        code,
        count=1
    )

    if f"public class {class_name}" not in code:
        code = re.sub(
            r"\bclass\s+[A-Za-z0-9_]+",
            f"public class {class_name}",
            code,
            count=1
        )

    return code


def remove_problematic_imports(code):
    lines = str(code).splitlines()
    cleaned = []

    remove_prefixes = [
        "import com.codeborne.selenide",
        "import org.junit.jupiter.api",
        "import org.openqa.selenium",
        "import org.hamcrest",
        "import static com.codeborne.selenide",
        "import static org.junit.jupiter.api",
        "import static org.hamcrest"
    ]

    for line in lines:
        stripped = line.strip()
        if any(stripped.startswith(prefix) for prefix in remove_prefixes):
            continue
        cleaned.append(line)

    return "\n".join(cleaned)


def add_standard_imports(code):
    imports = """
import com.codeborne.selenide.Configuration;
import com.codeborne.selenide.Condition;
import com.codeborne.selenide.ElementsCollection;
import com.codeborne.selenide.Selenide;
import com.codeborne.selenide.SelenideElement;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.openqa.selenium.By;
import org.openqa.selenium.Keys;

import static com.codeborne.selenide.CollectionCondition.*;
import static com.codeborne.selenide.Condition.*;
import static com.codeborne.selenide.Selectors.*;
import static com.codeborne.selenide.Selenide.*;
import static com.codeborne.selenide.WebDriverRunner.*;
import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.Matchers.*;
import static org.junit.jupiter.api.Assertions.*;
"""

    code = re.sub(
        r"(package org\.springframework\.samples\.petclinic;\s*)",
        r"\1\n" + imports + "\n",
        code,
        count=1
    )

    return code


def add_configuration_block(code):
    if "Configuration.baseUrl" in code:
        return code

    config_block = """
    private void objective1Configure() {
        Configuration.baseUrl = "http://localhost:8080";
        Configuration.browser = "chrome";
        Configuration.headless = true;
        Configuration.timeout = 10000;
    }

"""

    code = re.sub(r"(public class [A-Za-z0-9_]+\s*\{\s*)", r"\1\n" + config_block, code, count=1)

    methods = re.finditer(r"@Test\s*\n\s*(?:public\s+)?void\s+[A-Za-z0-9_]+\s*\([^)]*\)\s*\{", code)
    inserts = []
    for m in methods:
        inserts.append(m.end())

    if inserts:
        chars = list(code)
        offset = 0
        for pos in inserts:
            insert_text = "\n        objective1Configure();\n"
            chars.insert(pos + offset, insert_text)
            offset += len(insert_text)
        code = "".join(chars)

    return code


def phase1_basic_repair(raw_code, class_name):
    code = normalize_package_and_class(raw_code, class_name)
    code = remove_problematic_imports(code)
    code = add_standard_imports(code)
    code = add_configuration_block(code)
    return code


def phase2_api_repair(code):
    s = str(code)

    replacements = {
        "byCssSelector(": "By.cssSelector(",
        "byXpath(": "By.xpath(",
        "byXPath(": "By.xpath(",
        "byId(": "By.id(",
        "byName(": "By.name(",
        "byTagName(": "By.tagName(",
        "byLinkText(": "By.linkText(",
        "getCurrentUrl()": "url()",
        "currentUrl()": "url()",
        ".shouldBeVisible()": ".shouldBe(visible)",
        ".shouldNotBeVisible()": ".shouldNotBe(visible)",
        ".shouldExist()": ".should(exist)",
        ".shouldNotExist()": ".shouldNot(exist)",
        ".shouldContain(text(": ".shouldHave(text(",
        ".shouldNotContain(text(": ".shouldNotHave(text("
    }

    for old, new in replacements.items():
        s = s.replace(old, new)

    s = re.sub(
        r"\.shouldHaveText\s*\(\s*\"([^\"]*)\"\s*\)",
        r'.shouldHave(text("\1"))',
        s
    )

    s = re.sub(
        r"\.shouldContain\s*\(\s*\"([^\"]*)\"\s*\)",
        r'.shouldHave(text("\1"))',
        s
    )

    s = re.sub(
        r"\.shouldNotContain\s*\(\s*\"([^\"]*)\"\s*\)",
        r'.shouldNotHave(text("\1"))',
        s
    )

    s = re.sub(
        r"open\s*\(\s*\"http://localhost:8080([^\"]*)\"\s*\)",
        r'open("\1")',
        s
    )

    s = re.sub(
        r"open\s*\(\s*\"http://127.0.0.1:8080([^\"]*)\"\s*\)",
        r'open("\1")',
        s
    )

    s = re.sub(
        r"assertThat\s*\(\s*url\s*\(\s*\)\s*,\s*containsString\s*\(",
        r"assertThat(url(), containsString(",
        s
    )

    # v2 fixes from actual Spring compilation logs
    s = re.sub(
        r"\.shouldHaveSizeGreaterThan\s*\(\s*(\d+)\s*\)",
        r".shouldHave(sizeGreaterThan(\1))",
        s
    )

    s = re.sub(
        r"(\$\([^;\n]+?\))\.hasText\s*\(\s*\"([^\"]*)\"\s*\)",
        r"\1.getText().contains(\"\2\")",
        s
    )

    s = re.sub(
        r"([A-Za-z_][A-Za-z0-9_]*)\.hasText\s*\(\s*\"([^\"]*)\"\s*\)",
        r"\1.getText().contains(\"\2\")",
        s
    )

    s = re.sub(
        r"\$\(([^;\n]+?)\)\.get\s*\(\s*(\d+)\s*\)",
        r"$$($1).get($2)",
        s
    )

    return s


def phase3_syntax_type_repair(code):
    s = str(code)

    s = s.replace(";;", ";")

    s = re.sub(r"assertEquals\s*\(\s*url\s*\(\s*\)\s*,", "assertEquals(", s)

    s = re.sub(
        r"assertTrue\s*\(\s*\$\(\"body\"\)\.shouldHave\s*\(",
        r'$("body").shouldHave(',
        s
    )

    s = re.sub(
        r"driver\.findElement\s*\(",
        "$(",
        s
    )

    s = re.sub(
        r"webDriver\.findElement\s*\(",
        "$(",
        s
    )

    s = re.sub(
        r"getWebDriver\s*\(\s*\)\.findElement\s*\(",
        "$(",
        s
    )

    return s


def compile_code(class_name, code, repair_record_id, phase_name, env):
    remove_generated_test_leftovers()

    test_file = TEST_DIR / f"{class_name}.java"
    log_path = LOG_DIR / f"{repair_record_id}_{phase_name}_compile.log"

    write_text(test_file, code)

    mvnw = PROJECT_ROOT / "mvnw.cmd"
    maven_cmd = [str(mvnw)] if mvnw.exists() else ["mvn"]

    command = maven_cmd + [
        "-q",
        "-DskipTests",
        "-DfailIfNoTests=false",
        "-Dspring-javaformat.skip=true",
        "test-compile"
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

    combined = str(stdout) + "\n" + str(stderr)

    status = "Passed" if returncode == 0 and not timeout else "Failed"
    reason = "CompiledSuccessfully" if status == "Passed" else classify_compile_failure(combined)

    log_text = (
        "Repair Record ID: " + str(repair_record_id) +
        "\nClass Name: " + class_name +
        "\nPhase: " + phase_name +
        "\nCommand: " + " ".join(command) +
        "\nReturn Code: " + str(returncode) +
        "\nCompile Status: " + status +
        "\nCompile Reason: " + reason +
        "\nTimeout: " + str(timeout) +
        "\n\nSTDOUT:\n" + str(stdout) +
        "\n\nSTDERR:\n" + str(stderr)
    )

    write_text(log_path, log_text)

    try:
        if test_file.exists():
            test_file.unlink()
    except Exception:
        pass

    return status, reason, log_path, extract_first_error(combined)


def repair_one(row, env):
    repair_record_id = str(row.get("repair_record_id", "UNKNOWN"))
    workflow_id = str(row.get("workflow_id", "UNKNOWN"))
    model_provider = str(row.get("model_provider", "UNKNOWN"))

    src, src_col = resolve_source_path(row)

    if src is None:
        return {
            "spring_compile_repair_status": "Skipped",
            "spring_compile_repair_reason": "SourceCodePathNotFound",
            "spring_compile_repair_phase": "",
            "spring_repaired_code_path": "",
            "spring_repaired_class_name": "",
            "spring_compile_log_path": "",
            "spring_first_compile_error": "",
            "spring_source_column_used": ""
        }

    raw = read_text(src)

    class_name = "SPC_CompileRepair_" + safe_name(repair_record_id) + "_" + safe_name(workflow_id) + "_IT"

    phases = []

    code1 = phase1_basic_repair(raw, class_name)
    phases.append(("Phase1_BasicImportPackageClassRepair", code1))

    code2 = phase2_api_repair(code1)
    phases.append(("Phase2_SelenideSeleniumApiRepair", code2))

    code3 = phase3_syntax_type_repair(code2)
    phases.append(("Phase3_SyntaxTypeRepair", code3))

    last_status = "Failed"
    last_reason = ""
    last_log = ""
    last_error = ""
    final_code = code3
    final_phase = "AllPhasesFailed"

    for phase_name, phase_code in phases:
        status, reason, log_path, first_error = compile_code(
            class_name,
            phase_code,
            repair_record_id,
            phase_name,
            env
        )

        last_status = status
        last_reason = reason
        last_log = str(log_path)
        last_error = first_error
        final_code = phase_code
        final_phase = phase_name

        if status == "Passed":
            break

    repaired_code_path = REPAIR_DIR / repair_record_id / f"{class_name}.java"
    write_text(repaired_code_path, final_code)

    return {
        "spring_compile_repair_status": last_status,
        "spring_compile_repair_reason": last_reason,
        "spring_compile_repair_phase": final_phase,
        "spring_repaired_code_path": str(repaired_code_path),
        "spring_repaired_class_name": class_name,
        "spring_compile_log_path": last_log,
        "spring_first_compile_error": last_error,
        "spring_source_column_used": src_col
    }


def main():
    print("Spring compilation repair for remaining failed tests")
    print("=" * 90)

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    df = pd.read_csv(INPUT_FILE, encoding="utf-8")

    target = df[
        (df["workflow_id"].astype(str).str.startswith("SPC-WF")) &
        (df["compile_status"].astype(str).eq("Failed"))
    ].copy()

    print("Spring compilation-failed tests selected:", len(target))

    env = get_env()
    output_rows = []

    for idx, row in target.iterrows():
        repair_record_id = str(row.get("repair_record_id", f"ROW_{idx}"))
        workflow_id = str(row.get("workflow_id", "UNKNOWN"))
        model_provider = str(row.get("model_provider", "UNKNOWN"))

        print("\nRepairing", len(output_rows) + 1, "of", len(target), ":", repair_record_id, workflow_id, model_provider)

        result = repair_one(row, env)

        output = row.to_dict()
        output.update(result)

        print("Compile repair:", result["spring_compile_repair_status"], "-", result["spring_compile_repair_reason"], "-", result["spring_compile_repair_phase"])

        output_rows.append(output)

        pd.DataFrame(output_rows).to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    out = pd.DataFrame(output_rows)
    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    remove_generated_test_leftovers()

    print("\nSPRING COMPILATION REPAIR COMPLETED")
    print("=" * 90)

    print("\nCompile repair status:")
    print(out["spring_compile_repair_status"].value_counts(dropna=False))

    print("\nCompile repair reason:")
    print(out["spring_compile_repair_reason"].value_counts(dropna=False))

    print("\nRepair phase:")
    print(out["spring_compile_repair_phase"].value_counts(dropna=False))

    print("\nWorkflow-wise compile repair status:")
    print(pd.crosstab(out["workflow_id"], out["spring_compile_repair_status"]))

    print("\nModel-wise compile repair status:")
    print(pd.crosstab(out["model_provider"], out["spring_compile_repair_status"]))

    total = len(out)
    passed = (out["spring_compile_repair_status"] == "Passed").sum()
    failed = (out["spring_compile_repair_status"] == "Failed").sum()
    skipped = (out["spring_compile_repair_status"] == "Skipped").sum()

    print("\nNUMERIC SUMMARY")
    print("=" * 90)
    print("Total Spring compilation-failed tests selected:", total)
    print("Compile passed after Spring repair:", passed)
    print("Compile failed after Spring repair:", failed)
    print("Skipped:", skipped)

    if total > 0:
        print("Spring compilation repair success rate:", round((passed / total) * 100, 2), "%")

    print("\nOutput file:", OUTPUT_FILE)
    print("Repair code dir:", REPAIR_DIR)
    print("Log dir:", LOG_DIR)
    print("\nDONE")


if __name__ == "__main__":
    main()