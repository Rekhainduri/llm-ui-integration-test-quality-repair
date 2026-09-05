import os
import re
import subprocess
import sys
import pandas as pd
from pathlib import Path

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()

INPUT_FILE = ROOT / "csv_dataset" / "objective1_helpdesk_classpath_fixed_compile_targets.csv"
OUTPUT_FILE = ROOT / "csv_dataset" / "objective1_helpdesk_compilation_repair_v5_results.csv"

PROJECT_ROOT = ROOT / "projects" / "HelpDeskApp"
TEST_ROOT = PROJECT_ROOT / "src" / "test" / "java"

REPAIR_DIR = ROOT / "repair_workspace" / "helpdesk_compilation_repair_v5"
LOG_DIR = ROOT / "repair_workspace" / "helpdesk_compilation_repair_v5_logs"

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


def cleanup_temp_tests():
    if not TEST_ROOT.exists():
        return

    patterns = [
        "HD_ClasspathFixed_*.java",
        "HD_CompileRepairV2_*.java",
        "HD_CompileRepairV5_*.java",
    ]

    for pattern in patterns:
        for file in TEST_ROOT.rglob(pattern):
            try:
                file.unlink()
            except Exception:
                pass


def resolve_source_path(row):
    for col in ["final_repaired_code_path", "repaired_code_path", "generated_test_code_path", "original_code_path"]:
        value = str(row.get(col, "")).strip()
        if value and value.lower() != "nan" and Path(value).exists():
            return Path(value), col
    return None, ""


def extract_package_name(code):
    m = re.search(r"^\s*package\s+([A-Za-z0-9_.]+)\s*;", str(code), flags=re.MULTILINE)
    return m.group(1).strip() if m else "com.research.helpdesk"


def extract_class_name(code):
    m = re.search(r"\bpublic\s+class\s+([A-Za-z0-9_]+)", str(code))
    if m:
        return m.group(1).strip()

    m = re.search(r"\bclass\s+([A-Za-z0-9_]+)", str(code))
    return m.group(1).strip() if m else ""


def normalize_class(code, new_class_name):
    code = str(code).replace("\ufeff", "")
    old_class = extract_class_name(code)

    if old_class:
        code = re.sub(r"\bpublic\s+class\s+" + re.escape(old_class), "public class " + new_class_name, code, count=1)
        code = re.sub(r"\bclass\s+" + re.escape(old_class), "class " + new_class_name, code, count=1)
        code = re.sub(r"\b" + re.escape(old_class) + r"\s*\(", new_class_name + "(", code)
    else:
        code += f"\n\npublic class {new_class_name} {{\n}}\n"

    return code


def inject_imports(code):
    imports = """
import com.codeborne.selenide.Condition;
import com.codeborne.selenide.Configuration;
import com.codeborne.selenide.ElementsCollection;
import com.codeborne.selenide.Selenide;
import com.codeborne.selenide.SelenideElement;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.openqa.selenium.By;

import static com.codeborne.selenide.CollectionCondition.*;
import static com.codeborne.selenide.Condition.*;
import static com.codeborne.selenide.Selectors.*;
import static com.codeborne.selenide.Selenide.*;
import static org.junit.jupiter.api.Assertions.*;
"""

    if "package " in code:
        code = re.sub(r"(package\s+[A-Za-z0-9_.]+\s*;\s*)", r"\1\n" + imports + "\n", code, count=1)
    else:
        code = "package com.research.helpdesk;\n\n" + imports + "\n" + code

    return code


def add_config(code):
    if "Configuration.baseUrl" in code:
        return code

    block = """
    private void objective1Configure() {
        Configuration.baseUrl = "http://localhost:8083";
        Configuration.browser = "chrome";
        Configuration.headless = true;
        Configuration.timeout = 10000;
    }

"""

    code = re.sub(r"(public class [A-Za-z0-9_]+\s*\{\s*)", r"\1\n" + block, code, count=1)

    matches = list(re.finditer(r"@Test\s*\n\s*(?:public\s+)?void\s+[A-Za-z0-9_]+\s*\([^)]*\)\s*\{", code))
    chars = list(code)
    offset = 0

    for m in matches:
        insert = "\n        objective1Configure();\n"
        chars.insert(m.end() + offset, insert)
        offset += len(insert)

    return "".join(chars)


def api_repair(code):
    s = str(code)

    s = s.replace("byId(", "By.id(")
    s = s.replace("byName(", "By.name(")
    s = s.replace("byCssSelector(", "By.cssSelector(")
    s = s.replace("byXpath(", "By.xpath(")
    s = s.replace("byXPath(", "By.xpath(")

    # SelenideElement.find(text("x")) / findBy(text("x")) is invalid.
    s = re.sub(
        r"(?<!\$)(\$\([^;\n]+?\))\.findBy\s*\(\s*(?:Condition\.)?text\s*\(\s*(\"[^\"]*\")\s*\)\s*\)",
        r"\1.find(byText(\2))",
        s
    )

    s = re.sub(
        r"(?<!\$)(\$\([^;\n]+?\))\.find\s*\(\s*(?:Condition\.)?text\s*\(\s*(\"[^\"]*\")\s*\)\s*\)",
        r"\1.find(byText(\2))",
        s
    )

    # Variable-based element.findBy(text("x")).
    s = re.sub(
        r"([A-Za-z_][A-Za-z0-9_]*)\.findBy\s*\(\s*(?:Condition\.)?text\s*\(\s*(\"[^\"]*\")\s*\)\s*\)",
        r"\1.find(byText(\2))",
        s
    )

    s = re.sub(
        r"([A-Za-z_][A-Za-z0-9_]*)\.find\s*\(\s*(?:Condition\.)?text\s*\(\s*(\"[^\"]*\")\s*\)\s*\)",
        r"\1.find(byText(\2))",
        s
    )

    # SelenideElement.find(visible/enabled/exist) is invalid.
    s = re.sub(
        r"\.findBy\s*\(\s*(Condition\.)?(visible|enabled|exist|appear)\s*\)",
        r".shouldBe(\2)",
        s
    )

    s = re.sub(
        r"\.find\s*\(\s*(Condition\.)?(visible|enabled|exist|appear)\s*\)",
        r".shouldBe(\2)",
        s
    )

    # Invalid $("selector", text("x")).
    s = re.sub(
        r"\$\(\s*(\"[^\"]+\"|By\.[^)]+\))\s*,\s*((?:Condition\.)?text\([^)]*\)|visible|enabled|exist|appear)\s*\)",
        r"$(\1).shouldHave(\2)",
        s
    )

    # Collection size repairs.
    s = re.sub(r"\.shouldHaveSizeGreaterThan\s*\(\s*(\d+)\s*\)", r".shouldHave(sizeGreaterThan(\1))", s)
    s = re.sub(r"\.shouldHaveSize\s*\(\s*(\d+)\s*\)", r".shouldHave(size(\1))", s)

    # Collection shouldNotHave(text(...)) repair only for $$ selectors.
    s = re.sub(
        r"(\$\$\([^;\n]+?\))\.shouldNotHave\s*\(\s*((?:Condition\.)?text\([^)]*\)|visible|enabled|exist|appear)\s*\)",
        r"\1.filterBy(\2).shouldHave(size(0))",
        s
    )

    # Selenide 7 timeout as int is invalid.
    s = re.sub(r"\.shouldBe\s*\(\s*([^,\n]+)\s*,\s*\d+\s*\)", r".shouldBe(\1)", s)
    s = re.sub(r"\.shouldHave\s*\(\s*([^,\n]+)\s*,\s*\d+\s*\)", r".shouldHave(\1)", s)
    s = re.sub(r"\.shouldNotHave\s*\(\s*([^,\n]+)\s*,\s*\d+\s*\)", r".shouldNotHave(\1)", s)

    s = s.replace("getCurrentUrl()", "url()")
    s = s.replace("currentUrl()", "url()")

    s = re.sub(r"open\s*\(\s*\"http://localhost:8083([^\"]*)\"\s*\)", r'open("\1")', s)
    s = re.sub(r"open\s*\(\s*\"http://localhost:8080([^\"]*)\"\s*\)", r'open("\1")', s)


    # V5 additional repair rules based on rows 31-58 failure analysis

    # Condition.size(int) is invalid; use CollectionCondition.size(int) through static import.
    s = re.sub(r"\bCondition\.size\s*\(", "size(", s)

    # Selenide.clearBrowserCache() is not available in this version.
    s = re.sub(r"\bSelenide\.clearBrowserCache\s*\(\s*\)\s*;", "clearBrowserCookies();", s)
    s = re.sub(r"\bclearBrowserCache\s*\(\s*\)\s*;", "clearBrowserCookies();", s)

    # getSelectedText() is not available for SelenideElement in this setup.
    s = re.sub(r"\.getSelectedText\s*\(\s*\)", ".getText()", s)

    # Remaining findBy(text("x")) and find(text("x")) patterns.
    s = re.sub(
        r"\.findBy\s*\(\s*(?:Condition\.)?text\s*\(\s*(\"[^\"]*\")\s*\)\s*\)",
        r".find(byText(\1))",
        s
    )

    s = re.sub(
        r"\.find\s*\(\s*(?:Condition\.)?text\s*\(\s*(\"[^\"]*\")\s*\)\s*\)",
        r".find(byText(\1))",
        s
    )

    # Remaining find(visible), find(enabled), find(exist), find(appear)
    s = re.sub(
        r"\.findBy\s*\(\s*(?:Condition\.)?(visible|enabled|exist|appear)\s*\)",
        r".shouldBe(\1)",
        s
    )

    s = re.sub(
        r"\.find\s*\(\s*(?:Condition\.)?(visible|enabled|exist|appear)\s*\)",
        r".shouldBe(\1)",
        s
    )

    # element.find("selector", condition) is invalid.
    s = re.sub(
        r"\.find\s*\(\s*(\"[^\"]+\"|By\.[^)]+\))\s*,\s*((?:Condition\.)?text\([^)]*\)|(?:Condition\.)?(?:visible|enabled|exist|appear))\s*\)",
        r".find(\1).shouldHave(\2)",
        s
    )

    # element.$("selector", condition) is invalid.
    s = re.sub(
        r"\.\$\s*\(\s*(\"[^\"]+\"|By\.[^)]+\))\s*,\s*((?:Condition\.)?text\([^)]*\)|(?:Condition\.)?(?:visible|enabled|exist|appear))\s*\)",
        r".$(\1).shouldHave(\2)",
        s
    )

    # $(text("x")) is invalid; use $(byText("x")).
    s = re.sub(
        r"(?<![\$\w\.])\$\(\s*(?:Condition\.)?text\s*\(\s*(\"[^\"]*\")\s*\)\s*\)",
        r"$(byText(\1))",
        s
    )

    # element.$(text("x")) is invalid; use element.find(byText("x")).
    s = re.sub(
        r"\.\$\s*\(\s*(?:Condition\.)?text\s*\(\s*(\"[^\"]*\")\s*\)\s*\)",
        r".find(byText(\1))",
        s
    )

    # element.$(visible/enabled/exist/appear) is invalid.
    s = re.sub(
        r"\.\$\s*\(\s*(?:Condition\.)?(visible|enabled|exist|appear)\s*\)",
        r".shouldBe(\1)",
        s
    )

    # $("selector").last() should be $$("selector").last()
    s = re.sub(
        r"(?<!\$)\$\(([^;\n]+?)\)\.last\s*\(\s*\)",
        r"$$(\1).last()",
        s
    )

    # Chained element.find(...).last() is invalid; keep the found element.
    s = re.sub(
        r"(\.find\([^;\n]+?\))\.last\s*\(\s*\)",
        r"\1",
        s
    )

    # $("selector").get(i) should be $$("selector").get(i)
    s = re.sub(
        r"(?<!\$)\$\(([^;\n]+?)\)\.get\s*\(\s*(\d+)\s*\)",
        r"$$(\1).get(\2)",
        s
    )

    # Chained element.find(...).get(i) is invalid; keep the found element.
    s = re.sub(
        r"(\.find\([^;\n]+?\))\.get\s*\(\s*\d+\s*\)",
        r"\1",
        s
    )

    # assertTrue($("...")) is invalid because SelenideElement is not boolean.
    s = re.sub(
        r"assertTrue\s*\(\s*([^;\n]*\$\([^;\n]+?\))\s*\)\s*;",
        r"\1.shouldBe(visible);",
        s
    )

    s = re.sub(
        r"assertFalse\s*\(\s*([^;\n]*\$\([^;\n]+?\))\s*\)\s*;",
        r"\1.shouldNotBe(visible);",
        s
    )


    # V5 final aggressive Selenide API normalization

    # Avoid accidental resolution as org.junit.jupiter.api.Assertions.$ or Assertions.$$
    s = re.sub(r"\bAssertions\.\$\$\s*\(", "$$(", s)
    s = re.sub(r"\bAssertions\.\$\s*\(", "$(", s)

    # Replace findBy(condition) with shouldHave(condition), except By/byText selectors.
    s = re.sub(
        r"\.findBy\s*\(\s*((?!(?:By|byText|byId|byName|byCssSelector|byXpath)\b)(?:Condition\.)?[A-Za-z_][A-Za-z0-9_]*\s*\([^;\n]*?\)|(?:Condition\.)?(?:visible|enabled|exist|appear|hidden|disabled|selected|empty))\s*\)",
        r".shouldHave(\1)",
        s
    )

    # Replace find(condition) with shouldHave(condition), except String/By/byText selectors.
    s = re.sub(
        r"\.find\s*\(\s*((?!(?:By|byText|byId|byName|byCssSelector|byXpath)\b)(?:Condition\.)?[A-Za-z_][A-Za-z0-9_]*\s*\([^;\n]*?\)|(?:Condition\.)?(?:visible|enabled|exist|appear|hidden|disabled|selected|empty))\s*\)",
        r".shouldHave(\1)",
        s
    )

    # element.find("selector", condition) -> element.find("selector").shouldHave(condition)
    s = re.sub(
        r"\.find\s*\(\s*(\"[^\"]+\"|By\.[^)]+\))\s*,\s*((?:Condition\.)?[A-Za-z_][A-Za-z0-9_]*\s*\([^;\n]*?\)|(?:Condition\.)?(?:visible|enabled|exist|appear|hidden|disabled|selected|empty))\s*\)",
        r".find(\1).shouldHave(\2)",
        s
    )

    # element.$("selector", condition) -> element.$("selector").shouldHave(condition)
    s = re.sub(
        r"\.\$\s*\(\s*(\"[^\"]+\"|By\.[^)]+\))\s*,\s*((?:Condition\.)?[A-Za-z_][A-Za-z0-9_]*\s*\([^;\n]*?\)|(?:Condition\.)?(?:visible|enabled|exist|appear|hidden|disabled|selected|empty))\s*\)",
        r".$(\1).shouldHave(\2)",
        s
    )

    # $(text("x")) or $(exactText("x")) -> $(byText("x"))
    s = re.sub(
        r"(?<![\$\w\.])\$\(\s*(?:Condition\.)?(?:text|exactText|textCaseSensitive)\s*\(\s*(\"[^\"]*\")\s*\)\s*\)",
        r"$(byText(\1))",
        s
    )

    # element.$(text("x")) -> element.find(byText("x"))
    s = re.sub(
        r"\.\$\s*\(\s*(?:Condition\.)?(?:text|exactText|textCaseSensitive)\s*\(\s*(\"[^\"]*\")\s*\)\s*\)",
        r".find(byText(\1))",
        s
    )

    # element.$(visible/enabled/exist/appear) -> element.shouldBe(...)
    s = re.sub(
        r"\.\$\s*\(\s*(?:Condition\.)?(visible|enabled|exist|appear|hidden|disabled|selected|empty)\s*\)",
        r".shouldBe(\1)",
        s
    )

    # $("selector").last() -> $$("selector").last()
    s = re.sub(
        r"(?<!\$)\$\((\"[^\"]+\"|By\.[^)]+)\)\.last\s*\(\s*\)",
        r"$$(\1).last()",
        s
    )

    # $("selector").get(i) -> $$("selector").get(i)
    s = re.sub(
        r"(?<!\$)\$\((\"[^\"]+\"|By\.[^)]+)\)\.get\s*\(\s*(\d+)\s*\)",
        r"$$(\1).get(\2)",
        s
    )

    # If previous rule created collection.$$("x"), simplify to collection.findBy(text("x")) not nested $$.
    s = re.sub(
        r"(\$\$\([^;\n]+?\))\.\$\$\s*\(\s*\"([^\"]+)\"\s*\)",
        r"\1.filterBy(text(\2))",
        s
    )

    # SelenideElement.shouldHave(size(n)) is invalid. For element-level checks, convert to visible.
    s = re.sub(
        r"(?<!\$)\$\(([^;\n]+?)\)\.shouldHave\s*\(\s*size\s*\(\s*\d+\s*\)\s*\)",
        r"$(\1).shouldBe(visible)",
        s
    )

    s = re.sub(
        r"(\.find\([^;\n]+?\))\.shouldHave\s*\(\s*size\s*\(\s*\d+\s*\)\s*\)",
        r"\1.shouldBe(visible)",
        s
    )

    # Boolean dereference repairs: isDisplayed().should... / exists().should...
    s = re.sub(r"\.isDisplayed\s*\(\s*\)\.shouldBe\s*\(", ".shouldBe(", s)
    s = re.sub(r"\.isDisplayed\s*\(\s*\)\.shouldHave\s*\(", ".shouldHave(", s)
    s = re.sub(r"\.exists\s*\(\s*\)\.shouldBe\s*\(", ".shouldBe(", s)
    s = re.sub(r"\.exists\s*\(\s*\)\.shouldHave\s*\(", ".shouldHave(", s)

    # assertTrue(element) / assertFalse(element) where element is Selenide expression.
    s = re.sub(
        r"assertTrue\s*\(\s*([^;\n]*\$\([^;\n]+?\)[^;\n]*)\s*\)\s*;",
        r"\1.shouldBe(visible);",
        s
    )

    s = re.sub(
        r"assertFalse\s*\(\s*([^;\n]*\$\([^;\n]+?\)[^;\n]*)\s*\)\s*;",
        r"\1.shouldNotBe(visible);",
        s
    )

    # Common unsupported browser cache method
    s = re.sub(r"\bSelenide\.clearBrowserCache\s*\(\s*\)\s*;", "clearBrowserCookies();", s)
    s = re.sub(r"\bclearBrowserCache\s*\(\s*\)\s*;", "clearBrowserCookies();", s)

    # getSelectedText() not available here
    s = re.sub(r"\.getSelectedText\s*\(\s*\)", ".getText()", s)

    return s


def repair_code(raw_code, class_name):
    code = normalize_class(raw_code, class_name)
    code = inject_imports(code)
    code = api_repair(code)
    code = add_config(code)
    return code


def destination_for(package_name, class_name):
    return TEST_ROOT / package_name.replace(".", os.sep) / f"{class_name}.java"


def classify_compile_failure(text):
    t = str(text).lower()

    if "cannot find symbol" in t:
        return "CannotFindSymbol"
    if "no suitable method found" in t:
        return "MethodArgumentMismatch"
    if "package" in t and "does not exist" in t:
        return "PackageDoesNotExist"
    if "incompatible types" in t:
        return "IncompatibleTypes"
    if "class, interface, enum, or record expected" in t:
        return "MalformedJavaStructure"
    if "compilation failure" in t:
        return "MavenTestCompileFailure"
    if "timeout" in t:
        return "CompileTimeout"

    return "OtherCompilationFailure"


def extract_first_error(text):
    selected = []
    keys = ["[ERROR]", "cannot find symbol", "no suitable method", "symbol:", "location:", "compilation failure"]

    for line in str(text).splitlines():
        if any(k.lower() in line.lower() for k in keys):
            selected.append(re.sub(r"\s+", " ", line).strip()[:250])
        if len(selected) >= 12:
            break

    return " | ".join(selected)


def compile_one(row, env):
    rec = str(row.get("repair_record_id", "UNKNOWN"))
    wf = str(row.get("workflow_id", "UNKNOWN"))
    model = str(row.get("model_provider", "UNKNOWN"))

    src, src_col = resolve_source_path(row)

    if src is None:
        return {
            "helpdesk_v5_compile_status": "Skipped",
            "helpdesk_v5_compile_reason": "SourceCodePathNotFound",
            "helpdesk_v5_code_path": "",
            "helpdesk_v5_class_name": "",
            "helpdesk_v5_log_path": "",
            "helpdesk_v5_first_error": "",
            "helpdesk_v5_source_column": ""
        }

    raw = read_text(src)
    package_name = extract_package_name(raw)

    class_name = "HD_CompileRepairV5_" + safe_name(rec) + "_" + safe_name(wf) + "_IT"
    code = repair_code(raw, class_name)

    repair_code_path = REPAIR_DIR / rec / f"{class_name}.java"
    write_text(repair_code_path, code)

    cleanup_temp_tests()

    test_file = destination_for(package_name, class_name)
    write_text(test_file, code)

    log_path = LOG_DIR / f"{rec}_{wf}_{model}_compile_v5.log"

    command = [
        str(PROJECT_ROOT / "mvnw.cmd"),
        "-q",
        "-DskipTests",
        "-DfailIfNoTests=false",
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
        "Repair Record ID: " + rec +
        "\nWorkflow ID: " + wf +
        "\nModel Provider: " + model +
        "\nSource path: " + str(src) +
        "\nSource column: " + src_col +
        "\nClass name: " + class_name +
        "\nTemporary test file: " + str(test_file) +
        "\nCommand: " + " ".join(command) +
        "\nReturn Code: " + str(returncode) +
        "\nCompile Status: " + status +
        "\nCompile Reason: " + reason +
        "\n\nSTDOUT:\n" + str(stdout) +
        "\n\nSTDERR:\n" + str(stderr)
    )

    write_text(log_path, log_text)

    try:
        if test_file.exists():
            test_file.unlink()
    except Exception:
        pass

    cleanup_temp_tests()

    return {
        "helpdesk_v5_compile_status": status,
        "helpdesk_v5_compile_reason": reason,
        "helpdesk_v5_code_path": str(repair_code_path),
        "helpdesk_v5_class_name": class_name,
        "helpdesk_v5_log_path": str(log_path),
        "helpdesk_v5_first_error": extract_first_error(combined),
        "helpdesk_v5_source_column": src_col
    }


def main():
    print("HelpDesk compilation repair v5")
    print("=" * 90)

    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except Exception:
            limit = None

    df = pd.read_csv(INPUT_FILE, encoding="utf-8")

    if limit:
        df = df.head(limit).copy()
        print("Pilot limit:", limit)

    print("HelpDesk targets:", len(df))

    env = get_env()
    rows = []

    cleanup_temp_tests()

    for i, row in df.iterrows():
        rec = str(row.get("repair_record_id", f"ROW_{i}"))
        wf = str(row.get("workflow_id", "UNKNOWN"))
        model = str(row.get("model_provider", "UNKNOWN"))

        print("\nRepairing", len(rows) + 1, "of", len(df), ":", rec, wf, model)

        result = compile_one(row, env)

        out = row.to_dict()
        out.update(result)

        print("Compile:", result["helpdesk_v5_compile_status"], "-", result["helpdesk_v5_compile_reason"])

        rows.append(out)
        pd.DataFrame(rows).to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    cleanup_temp_tests()

    print("\nHELPDESK COMPILATION REPAIR V5 COMPLETED")
    print("=" * 90)

    print("\nCompile status:")
    print(out["helpdesk_v5_compile_status"].value_counts(dropna=False))

    print("\nCompile reason:")
    print(out["helpdesk_v5_compile_reason"].value_counts(dropna=False))

    print("\nWorkflow-wise compile status:")
    print(pd.crosstab(out["workflow_id"], out["helpdesk_v5_compile_status"]))

    print("\nModel-wise compile status:")
    print(pd.crosstab(out["model_provider"], out["helpdesk_v5_compile_status"]))

    total = len(out)
    passed = (out["helpdesk_v5_compile_status"] == "Passed").sum()
    failed = (out["helpdesk_v5_compile_status"] == "Failed").sum()
    skipped = (out["helpdesk_v5_compile_status"] == "Skipped").sum()

    print("\nNUMERIC SUMMARY")
    print("=" * 90)
    print("Total HelpDesk tests evaluated:", total)
    print("Compile passed after HelpDesk v5 repair:", passed)
    print("Compile failed after HelpDesk v5 repair:", failed)
    print("Skipped:", skipped)

    if total > 0:
        print("HelpDesk v5 compilation repair success rate:", round((passed / total) * 100, 2), "%")

    print("\nOutput file:", OUTPUT_FILE)
    print("Repair code dir:", REPAIR_DIR)
    print("Log dir:", LOG_DIR)
    print("\nDONE")


if __name__ == "__main__":
    main()