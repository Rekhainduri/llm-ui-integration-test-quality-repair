import os
import re
import shutil
import subprocess
import pandas as pd
from pathlib import Path

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()

INPUT_FILE = ROOT / "csv_dataset" / "objective1_bookstore_compilation_failure_analysis.csv"
OUTPUT_FILE = ROOT / "csv_dataset" / "objective1_bookstore_compilation_repair_progressive_final_results.csv"

REPAIR_DIR = ROOT / "repair_workspace" / "bookstore_compilation_repair_progressive_final"
LOG_DIR = ROOT / "repair_workspace" / "bookstore_compilation_repair_progressive_final_logs"

PROJECT_ROOT = ROOT / "projects" / "BookStore" / "Code" / "Online-Book-Store"
JAVA_HOME = Path(r"C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot")

TIMEOUT_SECONDS = 180


def get_environment():
    env = os.environ.copy()
    if JAVA_HOME.exists():
        env["JAVA_HOME"] = str(JAVA_HOME)
        env["PATH"] = str(JAVA_HOME / "bin") + os.pathsep + env.get("PATH", "")
    return env


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="ignore")


def sanitize_java_identifier(text):
    text = re.sub(r"[^A-Za-z0-9_]", "_", str(text))
    if re.match(r"^[0-9]", text):
        text = "_" + text
    return text


def find_source_code_path(row):
    possible_cols = [
        "final_repaired_code_path",
        "repaired_code_path",
        "stage2_repaired_code_path",
        "generated_test_code_path",
        "code_path"
    ]

    for col in possible_cols:
        if col in row.index:
            value = str(row.get(col, "")).strip()
            if value and value.lower() != "nan":
                p = Path(value)
                if p.exists() and p.suffix.lower() == ".java":
                    return p, col

    first_error = str(row.get("bookstore_first_compile_error", ""))
    m = re.search(r"([A-Za-z]:\\[^:]+?\.java):\d+:", first_error)
    if m:
        p = Path(m.group(1))
        if p.exists():
            return p, "bookstore_first_compile_error"

    return None, ""


def extract_package_name(code):
    m = re.search(r"^\s*package\s+([A-Za-z0-9_.]+)\s*;", code, flags=re.MULTILINE)
    return m.group(1).strip() if m else ""


def extract_class_name(code):
    m = re.search(r"\bpublic\s+class\s+([A-Za-z0-9_]+)", code)
    if m:
        return m.group(1).strip()

    m = re.search(r"\bclass\s+([A-Za-z0-9_]+)", code)
    return m.group(1).strip() if m else ""


def remove_markdown_fences(code):
    code = code.replace("```java", "")
    code = code.replace("```Java", "")
    code = code.replace("```", "")
    return code


def ensure_package(code):
    if re.search(r"^\s*package\s+", code, flags=re.MULTILINE):
        return code
    return "package com.online.book.store;\n\n" + code


def add_import_if_missing(code, import_line):
    if import_line in code:
        return code

    m = re.search(r"^\s*package\s+[A-Za-z0-9_.]+\s*;\s*", code, flags=re.MULTILINE)
    if m:
        return code[:m.end()] + "\n" + import_line + "\n" + code[m.end():]

    return import_line + "\n" + code


def add_required_imports(code):
    imports = [
        "import com.codeborne.selenide.Configuration;",
        "import com.codeborne.selenide.SelenideElement;",
        "import com.codeborne.selenide.ElementsCollection;",
        "import com.codeborne.selenide.WebDriverRunner;",
        "import org.junit.jupiter.api.Test;",
        "import org.openqa.selenium.By;",
        "import static com.codeborne.selenide.Selenide.*;",
        "import static com.codeborne.selenide.Condition.*;",
        "import static com.codeborne.selenide.CollectionCondition.*;",
        "import static com.codeborne.selenide.Selectors.*;",
        "import static org.junit.jupiter.api.Assertions.*;"
    ]

    for imp in imports:
        code = add_import_if_missing(code, imp)

    return code


def rename_public_class(code, new_class_name):
    old_class = extract_class_name(code)

    if old_class:
        code = re.sub(
            r"\bpublic\s+class\s+" + re.escape(old_class) + r"\b",
            "public class " + new_class_name,
            code,
            count=1
        )
    else:
        code += "\n\npublic class " + new_class_name + " {\n}\n"

    return code


def destination_for_test_file(package_name, class_name):
    test_root = PROJECT_ROOT / "src" / "test" / "java"
    if package_name:
        return test_root / package_name.replace(".", os.sep) / f"{class_name}.java"
    return test_root / f"{class_name}.java"


def backup_existing_file(path):
    if not path.exists():
        return None

    backup = path.with_suffix(path.suffix + ".objective1_progressive_backup")
    counter = 1

    while backup.exists():
        backup = path.with_suffix(path.suffix + f".objective1_progressive_backup_{counter}")
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


def run_command(command, cwd, env):
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=TIMEOUT_SECONDS,
            shell=False
        )
        return completed.returncode, completed.stdout, completed.stderr, False

    except subprocess.TimeoutExpired as e:
        return -999, e.stdout or "", e.stderr or "TIMEOUT", True

    except Exception as e:
        return -998, "", str(e), False


def classify_compile_result(returncode, stdout, stderr, timeout):
    combined = (str(stdout) + "\n" + str(stderr)).lower()

    if timeout:
        return "CompileTimeout"
    if returncode == 0:
        return "CompiledSuccessfully"
    if "cannot find symbol" in combined:
        return "CannotFindSymbol"
    if "incompatible types" in combined:
        return "IncompatibleTypes"
    if "cannot be applied to given types" in combined:
        return "MethodArgumentMismatch"
    if "';' expected" in combined:
        return "MissingSemicolon"
    if "compilation failure" in combined or "compilation error" in combined:
        return "JavacCompilationError"

    return "OtherCompilationFailure"


def compile_test(row, code, class_name, attempt_name, env):
    repair_record_id = str(row.get("repair_record_id", "UNKNOWN"))
    workflow_id = str(row.get("workflow_id", "UNKNOWN"))
    model_provider = str(row.get("model_provider", "UNKNOWN"))

    package_name = extract_package_name(code)

    repaired_path = (
        REPAIR_DIR
        / attempt_name
        / model_provider
        / repair_record_id
        / f"{class_name}.java"
    )
    write_text(repaired_path, code)

    destination_path = destination_for_test_file(package_name, class_name)
    log_path = LOG_DIR / f"{repair_record_id}_{workflow_id}_{model_provider}_{attempt_name}.log"

    backup = None

    try:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        backup = backup_existing_file(destination_path)
        write_text(destination_path, code)

        mvnw = PROJECT_ROOT / "mvnw.cmd"
        maven_cmd = [str(mvnw)] if mvnw.exists() else ["mvn"]

        command = maven_cmd + [
            "-q",
            "-DskipTests",
            "test-compile"
        ]

        returncode, stdout, stderr, timeout = run_command(command, PROJECT_ROOT, env)

        reason = classify_compile_result(returncode, stdout, stderr, timeout)
        status = "Passed" if reason == "CompiledSuccessfully" else "Failed"

        log_text = (
            "Repair Record ID: " + repair_record_id +
            "\nWorkflow ID: " + workflow_id +
            "\nModel Provider: " + model_provider +
            "\nAttempt: " + attempt_name +
            "\nRepaired code path: " + str(repaired_path) +
            "\nCopied test path: " + str(destination_path) +
            "\nCommand: " + " ".join(command) +
            "\nReturn Code: " + str(returncode) +
            "\nStatus: " + status +
            "\nReason: " + reason +
            "\n\nSTDOUT:\n" + str(stdout) +
            "\n\nSTDERR:\n" + str(stderr)
        )

        write_text(log_path, log_text)

        return status, reason, str(repaired_path), str(log_path)

    finally:
        restore_or_cleanup(destination_path, backup)


def stage1_basic_repair(code):
    notes = []

    code = remove_markdown_fences(code)
    code = ensure_package(code)
    code = add_required_imports(code)

    replacements = {
        "byId(": "By.id(",
        "byName(": "By.name(",
        "byCssSelector(": "By.cssSelector(",
        "byXpath(": "By.xpath(",
        "byXPath(": "By.xpath("
    }

    for old, new in replacements.items():
        if old in code:
            code = code.replace(old, new)
            notes.append(f"{old}->{new}")

    if "currentUrl()" in code:
        code = code.replace("currentUrl()", "WebDriverRunner.url()")
        notes.append("currentUrl()->WebDriverRunner.url()")

    pattern = r"(\$\([^;\n]+?\))\.shouldContain\(([^;\n]+?)\)"
    code, count = re.subn(
        pattern,
        lambda m: m.group(1) + ".shouldHave(text(" + m.group(2).strip() + "))",
        code
    )
    if count:
        notes.append(f"element_shouldContain->shouldHave_text_{count}")

    pattern = r"assertTrue\s*\(\s*(\$\([^;\n]+?\))\s*\)\s*;"
    code, count = re.subn(
        pattern,
        lambda m: m.group(1) + ".shouldBe(visible);",
        code
    )
    if count:
        notes.append(f"assertTrue_element->shouldBe_visible_{count}")

    if not notes:
        notes.append("Stage1OnlyImportsAndClassRename")

    return code, "; ".join(notes)


def stage2_advanced_api_repair(code):
    notes = []

    replacements = [
        ("webdriver().getCurrentUrl()", "WebDriverRunner.url()"),
        ("getCurrentUrl()", "WebDriverRunner.url()"),
        ("currentURL()", "WebDriverRunner.url()")
    ]

    for old, new in replacements:
        if old in code:
            code = code.replace(old, new)
            notes.append(f"{old}->{new}")

    pattern = r"([A-Za-z_][A-Za-z0-9_]*)\.shouldContain\(([^;\n]+?)\)\s*;"
    code, count = re.subn(
        pattern,
        lambda m: f"assertTrue({m.group(1)}.contains({m.group(2).strip()}));",
        code
    )
    if count:
        notes.append(f"variable_shouldContain->assertTrue_contains_{count}")

    pattern = r"([A-Za-z_][A-Za-z0-9_]*)\.should\s*\(\s*containsString\(([^;\n]+?)\)\s*\)\s*;"
    code, count = re.subn(
        pattern,
        lambda m: f"assertTrue({m.group(1)}.contains({m.group(2).strip()}));",
        code
    )
    if count:
        notes.append(f"containsString->assertTrue_contains_{count}")

    pattern = r"WebDriverRunner\.url\(\)\.shouldBe\s*\(\s*endsWith\(([^;\n]+?)\)\s*\)\s*;"
    code, count = re.subn(
        pattern,
        lambda m: f"assertTrue(WebDriverRunner.url().endsWith({m.group(1).strip()}));",
        code
    )
    if count:
        notes.append(f"url_endsWith->assertTrue_{count}")

    pattern = r"\burl\(\)\.shouldBe\s*\(([^;\n]+?)\)\s*;"
    code, count = re.subn(
        pattern,
        lambda m: f"assertEquals({m.group(1).strip()}, WebDriverRunner.url());",
        code
    )
    if count:
        notes.append(f"url_shouldBe->assertEquals_{count}")

    pattern = r"\bassertCurrentUrl\s*\(([^;\n]+?)\)\s*;"
    code, count = re.subn(
        pattern,
        lambda m: f"assertTrue(WebDriverRunner.url().contains({m.group(1).strip()}));",
        code
    )
    if count:
        notes.append(f"assertCurrentUrl->assertTrue_url_contains_{count}")

    pattern = r"\.shouldHaveSize\s*\(\s*greaterThan\((\d+)\)\s*\)"
    code, count = re.subn(
        pattern,
        lambda m: f".shouldHave(sizeGreaterThan({m.group(1)}))",
        code
    )
    if count:
        notes.append(f"shouldHaveSize_greaterThan->sizeGreaterThan_{count}")

    pattern = r"\.shouldHaveSize\s*\(\s*(\d+)\s*\)"
    code, count = re.subn(
        pattern,
        lambda m: f".shouldHave(size({m.group(1)}))",
        code
    )
    if count:
        notes.append(f"shouldHaveSize_int->size_{count}")

    pattern = r"\$\(([^;\n]+?)\)\.last\(\)"
    code, count = re.subn(
        pattern,
        lambda m: f"$$({m.group(1)}).last()",
        code
    )
    if count:
        notes.append(f"element_last->collection_last_{count}")

    pattern = r"\$\(([^;\n]+?)\)\.filterBy\("
    code, count = re.subn(
        pattern,
        lambda m: f"$$({m.group(1)}).filterBy(",
        code
    )
    if count:
        notes.append(f"element_filterBy->collection_filterBy_{count}")

    pattern = r"(\.filterBy\([^;\n]+?\))\.click\(\)"
    code, count = re.subn(pattern, r"\1.first().click()", code)
    if count:
        notes.append(f"filterBy_click->first_click_{count}")

    pattern = r"(\$\$\([^;\n]+?\))\.click\(\)"
    code, count = re.subn(pattern, r"\1.first().click()", code)
    if count:
        notes.append(f"collection_click->first_click_{count}")

    if ".texts().stream()" in code:
        code = code.replace(".texts().stream()", ".text().lines()")
        notes.append("texts_stream->text_lines")

    if ".getText()" in code:
        code = code.replace(".getText()", ".text()")
        notes.append("getText->text")

    if ".orHave(" in code:
        code = code.replace(".orHave(", ".shouldHave(")
        notes.append("orHave->shouldHave")

    if ".or(text(" in code:
        code = code.replace(".or(text(", ".shouldHave(text(")
        notes.append("or_text->shouldHave_text")

    pattern = r"\$\(([^;\n]+?)\)\.shouldBe\(visible\)\.or\(\$\(([^;\n]+?)\)\.shouldHave\(text\(([^;\n]+?)\)\)\)\s*;"
    code, count = re.subn(
        pattern,
        lambda m: f"assertTrue($({m.group(1).strip()}).exists() || $({m.group(2).strip()}).text().contains({m.group(3).strip()}));",
        code
    )
    if count:
        notes.append(f"or_visibility_text->assertTrue_{count}")

    if not notes:
        notes.append("Stage2NoRuleApplied")

    return code, "; ".join(notes)


def stage3_extra_type_syntax_repair(code, compile_reason):
    notes = []

    pattern = r"boolean\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\$\([^;\n]+?\))\s*;"
    code, count = re.subn(
        pattern,
        lambda m: f"boolean {m.group(1)} = {m.group(2)}.exists();",
        code
    )
    if count:
        notes.append(f"boolean_element_assignment->exists_{count}")

    pattern = r"boolean\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\$\$\([^;\n]+?\))\s*;"
    code, count = re.subn(
        pattern,
        lambda m: f"boolean {m.group(1)} = !{m.group(2)}.isEmpty();",
        code
    )
    if count:
        notes.append(f"boolean_collection_assignment->not_isEmpty_{count}")

    pattern = r"String\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\$\([^;\n]+?\))\s*;"
    code, count = re.subn(
        pattern,
        lambda m: f"String {m.group(1)} = {m.group(2)}.text();",
        code
    )
    if count:
        notes.append(f"String_element_assignment->text_{count}")

    pattern = r"int\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\$\$\([^;\n]+?\))\s*;"
    code, count = re.subn(
        pattern,
        lambda m: f"int {m.group(1)} = {m.group(2)}.size();",
        code
    )
    if count:
        notes.append(f"int_collection_assignment->size_{count}")

    pattern = r"(\$\([^;\n]+?\))\.isEmpty\(\)"
    code, count = re.subn(
        pattern,
        lambda m: "!" + m.group(1) + ".exists()",
        code
    )
    if count:
        notes.append(f"element_isEmpty->not_exists_{count}")

    if ".visible()" in code:
        code = code.replace(".visible()", ".isDisplayed()")
        notes.append("visible_method->isDisplayed")

    if "visible()" in code:
        code = code.replace("visible()", "visible")
        notes.append("visible_parentheses->visible")

    code, count = re.subn(r"\.click\s*;", ".click();", code)
    if count:
        notes.append(f"click_property->click_method_{count}")

    code, count = re.subn(r"\.exists\s*;", ".exists();", code)
    if count:
        notes.append(f"exists_property_statement->exists_method_{count}")

    code, count = re.subn(r"\.exists(?!\s*\()", ".exists()", code)
    if count:
        notes.append(f"exists_property->exists_method_{count}")

    code, count = re.subn(r"\.get\(\)", ".first()", code)
    if count:
        notes.append(f"get_empty->first_{count}")

    pattern = r"\.child\s*\(([^;\n]+?)\)"
    code, count = re.subn(
        pattern,
        lambda m: ".$(" + m.group(1).strip() + ")",
        code
    )
    if count:
        notes.append(f"child->selenide_child_{count}")

    pattern = r"(\$\([^;\n]+?\))\.shouldBe\s*\(\s*(\"[^\"]*\"|'[^']*')\s*\)"
    code, count = re.subn(
        pattern,
        lambda m: m.group(1) + ".shouldHave(text(" + m.group(2) + "))",
        code
    )
    if count:
        notes.append(f"shouldBe_string->shouldHave_text_{count}")

    code, count = re.subn(r"\.shouldBe\s*\(\s*text\(", ".shouldHave(text(", code)
    if count:
        notes.append(f"shouldBe_text->shouldHave_text_{count}")

    pattern = r"assertEquals\s*\(\s*([^,\n;]+?)\s*,\s*(\$\([^;\n]+?\))\s*\)\s*;"
    code, count = re.subn(
        pattern,
        lambda m: "assertEquals(" + m.group(1).strip() + ", " + m.group(2) + ".text());",
        code
    )
    if count:
        notes.append(f"assertEquals_element->assertEquals_text_{count}")

    if "MissingSemicolon" in str(compile_reason):
        code, semicolon_notes = add_simple_missing_semicolons(code)
        notes.extend(semicolon_notes)

    if not notes:
        notes.append("Stage3NoRuleApplied")

    return code, "; ".join(notes)


def add_simple_missing_semicolons(code):
    notes = []
    lines = code.splitlines()
    new_lines = []
    changed = 0

    skip_starts = (
        "if ", "if(", "for ", "for(", "while ", "while(",
        "switch ", "switch(", "try", "catch", "else",
        "public ", "private ", "protected ", "class ",
        "@", "//", "/*", "*", "package ", "import "
    )

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith(skip_starts):
            new_lines.append(line)
            continue

        if stripped.endswith((";", "{", "}", ",", ":", "+", "&&", "||")):
            new_lines.append(line)
            continue

        likely_statement = (
            stripped.startswith("assert")
            or stripped.startswith("open(")
            or stripped.startswith("closeWebDriver(")
            or stripped.startswith("sleep(")
            or stripped.startswith("$(")
            or stripped.startswith("$$(")
            or stripped.startswith("String ")
            or stripped.startswith("int ")
            or stripped.startswith("boolean ")
            or stripped.startswith("SelenideElement ")
            or stripped.startswith("ElementsCollection ")
            or ".should" in stripped
            or ".click()" in stripped
            or ".setValue(" in stripped
            or ".selectOption(" in stripped
            or ".exists()" in stripped
        )

        if likely_statement and stripped.endswith(")"):
            new_lines.append(line + ";")
            changed += 1
        else:
            new_lines.append(line)

    if changed:
        notes.append(f"missing_semicolon_added_{changed}")

    return "\n".join(new_lines), notes


def main():
    print("BookStore progressive final compilation-repair pipeline")
    print("=" * 80)

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input not found: {INPUT_FILE}")

    env = get_environment()
    print("JAVA_HOME:", env.get("JAVA_HOME", "Not set"))

    df = pd.read_csv(INPUT_FILE, encoding="utf-8")
    print("Total BookStore compilation-failed rows:", len(df))

    output_rows = []

    for index, row in df.iterrows():
        repair_record_id = str(row.get("repair_record_id", f"ROW_{index}"))
        workflow_id = str(row.get("workflow_id", "UNKNOWN"))
        model_provider = str(row.get("model_provider", "UNKNOWN"))
        compile_reason = str(row.get("compile_reason", ""))

        print(
            "\nProcessing",
            len(output_rows) + 1,
            "of",
            len(df),
            ":",
            repair_record_id,
            workflow_id,
            model_provider
        )

        output = row.to_dict()

        source_path, source_col = find_source_code_path(row)

        if source_path is None:
            output["progressive_source_code_path"] = ""
            output["progressive_source_code_column"] = ""
            output["progressive_final_status"] = "Skipped"
            output["progressive_final_reason"] = "SourceCodePathNotFound"
            output["progressive_success_stage"] = "Skipped"
            output["progressive_final_repaired_code_path"] = ""
            output["progressive_final_compile_log_path"] = ""
            output["stage1_status"] = "Skipped"
            output["stage2_status"] = "Skipped"
            output["stage3_status"] = "Skipped"
            output_rows.append(output)
            pd.DataFrame(output_rows).to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
            continue

        original_code = read_text(source_path)

        base_class_name = (
            "BS_"
            + sanitize_java_identifier(workflow_id)
            + "_"
            + sanitize_java_identifier(model_provider)
            + "_"
            + sanitize_java_identifier(repair_record_id)
        )

        output["progressive_source_code_path"] = str(source_path)
        output["progressive_source_code_column"] = source_col

        # Stage 1
        class_stage1 = base_class_name + "_ProgressiveStage1_IT"
        code1, notes1 = stage1_basic_repair(original_code)
        code1 = rename_public_class(code1, class_stage1)

        status1, reason1, path1, log1 = compile_test(
            row,
            code1,
            class_stage1,
            "stage1_basic",
            env
        )

        output["stage1_notes"] = notes1
        output["stage1_status"] = status1
        output["stage1_reason"] = reason1
        output["stage1_repaired_code_path"] = path1
        output["stage1_compile_log_path"] = log1

        print("Stage 1:", status1, "-", reason1)

        if status1 == "Passed":
            output["stage2_notes"] = ""
            output["stage2_status"] = "NotRun"
            output["stage2_reason"] = ""
            output["stage3_notes"] = ""
            output["stage3_status"] = "NotRun"
            output["stage3_reason"] = ""

            output["progressive_final_status"] = "Passed"
            output["progressive_final_reason"] = reason1
            output["progressive_success_stage"] = "Stage1BasicRepair"
            output["progressive_final_repaired_code_path"] = path1
            output["progressive_final_compile_log_path"] = log1

            output_rows.append(output)
            pd.DataFrame(output_rows).to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
            continue

        # Stage 2
        class_stage2 = base_class_name + "_ProgressiveStage2_IT"
        code2, notes2 = stage2_advanced_api_repair(code1)
        code2 = rename_public_class(code2, class_stage2)

        status2, reason2, path2, log2 = compile_test(
            row,
            code2,
            class_stage2,
            "stage2_advanced_api",
            env
        )

        output["stage2_notes"] = notes2
        output["stage2_status"] = status2
        output["stage2_reason"] = reason2
        output["stage2_repaired_code_path"] = path2
        output["stage2_compile_log_path"] = log2

        print("Stage 2:", status2, "-", reason2)

        if status2 == "Passed":
            output["stage3_notes"] = ""
            output["stage3_status"] = "NotRun"
            output["stage3_reason"] = ""

            output["progressive_final_status"] = "Passed"
            output["progressive_final_reason"] = reason2
            output["progressive_success_stage"] = "Stage2AdvancedAPIRepair"
            output["progressive_final_repaired_code_path"] = path2
            output["progressive_final_compile_log_path"] = log2

            output_rows.append(output)
            pd.DataFrame(output_rows).to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
            continue

        # Stage 3
        class_stage3 = base_class_name + "_ProgressiveStage3_IT"
        code3, notes3 = stage3_extra_type_syntax_repair(code2, reason2)
        code3 = rename_public_class(code3, class_stage3)

        status3, reason3, path3, log3 = compile_test(
            row,
            code3,
            class_stage3,
            "stage3_type_syntax",
            env
        )

        output["stage3_notes"] = notes3
        output["stage3_status"] = status3
        output["stage3_reason"] = reason3
        output["stage3_repaired_code_path"] = path3
        output["stage3_compile_log_path"] = log3

        print("Stage 3:", status3, "-", reason3)

        output["progressive_final_status"] = status3
        output["progressive_final_reason"] = reason3
        output["progressive_success_stage"] = "Stage3TypeSyntaxRepair" if status3 == "Passed" else "Unresolved"
        output["progressive_final_repaired_code_path"] = path3
        output["progressive_final_compile_log_path"] = log3

        output_rows.append(output)
        pd.DataFrame(output_rows).to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    out = pd.DataFrame(output_rows)
    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    print("\nBOOKSTORE PROGRESSIVE FINAL COMPILATION REPAIR COMPLETED")
    print("=" * 80)
    print("Output file:", OUTPUT_FILE)
    print("Repair dir:", REPAIR_DIR)
    print("Log dir:", LOG_DIR)

    print("\nProgressive final status:")
    print(out["progressive_final_status"].value_counts(dropna=False))

    print("\nProgressive final reason:")
    print(out["progressive_final_reason"].value_counts(dropna=False))

    print("\nSuccess stage distribution:")
    print(out["progressive_success_stage"].value_counts(dropna=False))

    print("\nModel-wise progressive final status:")
    print(pd.crosstab(out["model_provider"], out["progressive_final_status"]))

    print("\nWorkflow-wise progressive final status:")
    print(pd.crosstab(out["workflow_id"], out["progressive_final_status"]))

    total = len(out)
    passed = (out["progressive_final_status"] == "Passed").sum()
    failed = (out["progressive_final_status"] == "Failed").sum()
    skipped = (out["progressive_final_status"] == "Skipped").sum()

    print("\nNUMERIC SUMMARY")
    print("=" * 80)
    print("Total input rows:", total)
    print("Compile passed after progressive final repair:", passed)
    print("Compile failed after progressive final repair:", failed)
    print("Skipped:", skipped)

    if total > 0:
        print("Progressive final compilation repair success rate:", round((passed / total) * 100, 2), "%")

    print("\nDONE")


if __name__ == "__main__":
    main()