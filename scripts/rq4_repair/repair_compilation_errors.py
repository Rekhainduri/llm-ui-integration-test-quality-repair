import os
import re
import subprocess
import pandas as pd
from pathlib import Path
from collections import Counter

# ============================================================
# Objective 1: Final Consolidated Compilation Repair Script
# ============================================================
# This script repairs only Compilation Error cases.
#
# It performs:
# 1. Stage-1 repair:
#    - Remove markdown code fences
#    - Fix JUnit4 to JUnit5 imports
#    - Add missing Selenium/Selenide/JUnit imports
#    - Remove duplicate imports
#    - Ensure class visibility where possible
#
# 2. Stage-2 repair:
#    - Remove invalid Selenide static imports
#    - Repair invalid browser/CHROME assignments
#    - Repair wrong Selenide utility imports
#    - Repair shouldHaveValue()
#    - Repair first()
#    - Repair invalid By.or()
#    - Repair simple assertThat() patterns
#
# 3. Compile validation:
#    - Uses project Maven classpath
#    - Uses javac
#    - Does NOT overwrite original LLM-generated files
#
# Output:
#    csv_dataset\objective1_final_compilation_repair_results.csv
# ============================================================

ROOT = Path(os.environ.get("LLM_UI_RESEARCH_ROOT", ".")).resolve()

INPUT_FILE = ROOT / "csv_dataset" / "objective1_repair_pool_compilation_errors.csv"

OUTPUT_FILE = ROOT / "csv_dataset" / "objective1_final_compilation_repair_results.csv"

REPAIR_DIR = ROOT / "repair_workspace" / "final_compilation_repair"
VALIDATION_WORKSPACE = ROOT / "repair_workspace" / "final_compilation_compile_check"
LOG_DIR = ROOT / "repair_workspace" / "final_compilation_compile_logs"
CLASSPATH_CACHE_DIR = ROOT / "repair_workspace" / "maven_classpath_cache_final"

KNOWN_JAVA_HOME = Path(r"C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot")

TIMEOUT_SECONDS = 120

# Set to None for all rows.
# For testing, you can set MAX_ROWS = 50
MAX_ROWS = None

PROJECT_ROOTS = {
    "JPetStore 6": ROOT / "projects" / "JPetStore6",
    "BookStore": ROOT / "projects" / "BookStore" / "Code" / "Online-Book-Store",
    "HelpDeskApp": ROOT / "projects" / "HelpDeskApp",
    "Spring PetClinic": ROOT / "projects" / "spring-petclinic",
}


# ------------------------------------------------------------
# Basic file helpers
# ------------------------------------------------------------

def read_csv_safely(file_path):
    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return pd.read_csv(f)


def resolve_path(path_value):
    if pd.isna(path_value):
        return None

    path_text = str(path_value).strip()

    if path_text == "":
        return None

    p = Path(path_text)

    if not p.is_absolute():
        p = ROOT / path_text

    return p


def read_text_file(path_value):
    p = resolve_path(path_value)

    if p is None:
        return ""

    if not p.exists():
        return ""

    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def write_text_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8", errors="ignore") as f:
        f.write(text)


def make_safe_text(text):
    text = str(text).strip()
    text = text.replace(" ", "_")
    text = re.sub(r"[^A-Za-z0-9_\\-]", "_", text)
    return text


# ------------------------------------------------------------
# Code parsing helpers
# ------------------------------------------------------------

def clean_markdown_fences(code):
    original = code

    code = re.sub(r"^\s*```java\s*", "", code, flags=re.IGNORECASE | re.MULTILINE)
    code = re.sub(r"^\s*```\s*", "", code, flags=re.MULTILINE)

    changed = code != original

    return code.strip() + "\n", changed


def find_package_line_index(lines):
    for i, line in enumerate(lines):
        if line.strip().startswith("package "):
            return i

    return None


def find_last_import_index(lines):
    last_import = None

    for i, line in enumerate(lines):
        if line.strip().startswith("import "):
            last_import = i

    return last_import


def extract_class_name(code_text):
    public_match = re.search(r"\bpublic\s+class\s+([A-Za-z0-9_]+)", code_text)

    if public_match:
        return public_match.group(1).strip()

    class_match = re.search(r"\bclass\s+([A-Za-z0-9_]+)", code_text)

    if class_match:
        return class_match.group(1).strip()

    return ""


def ensure_public_class(code, notes):
    if re.search(r"\bpublic\s+class\s+[A-Za-z0-9_]+", code):
        return code

    updated = re.sub(
        r"(^|\n)(\s*)class\s+([A-Za-z0-9_]+)",
        r"\1\2public class \3",
        code,
        count=1
    )

    if updated != code:
        notes.append("MadeClassPublic")

    return updated


def remove_duplicate_imports(code, notes):
    lines = code.splitlines()
    seen = set()
    output = []
    duplicates = 0

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("import "):
            if stripped in seen:
                duplicates += 1
                continue

            seen.add(stripped)

        output.append(line)

    if duplicates > 0:
        notes.append(f"RemovedDuplicateImports:{duplicates}")

    return "\n".join(output).strip() + "\n"


def remove_import_lines(code, import_fragments, notes, note_name):
    lines = code.splitlines()
    output = []
    removed = 0

    for line in lines:
        stripped = line.strip()

        remove_line = False

        if stripped.startswith("import "):
            for fragment in import_fragments:
                if fragment in stripped:
                    remove_line = True
                    break

        if remove_line:
            removed += 1
            continue

        output.append(line)

    if removed > 0:
        notes.append(f"{note_name}:{removed}")

    return "\n".join(output).strip() + "\n"


def add_imports(code, imports_to_add, notes, note_name):
    if not imports_to_add:
        return code

    existing = set()

    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            existing.add(stripped)

    final_imports = []

    for imp in imports_to_add:
        imp = imp.strip()

        if not imp:
            continue

        imp_line = f"import {imp};"

        if imp_line not in existing:
            final_imports.append(imp_line)

    if not final_imports:
        return code

    lines = code.splitlines()

    last_import_index = find_last_import_index(lines)

    if last_import_index is not None:
        insert_index = last_import_index + 1
    else:
        package_index = find_package_line_index(lines)

        if package_index is not None:
            insert_index = package_index + 1
        else:
            insert_index = 0

    for imp_line in reversed(final_imports):
        lines.insert(insert_index, imp_line)

    notes.append(note_name)

    return "\n".join(lines).strip() + "\n"


# ------------------------------------------------------------
# Stage-1 repair rules
# ------------------------------------------------------------

def repair_junit4_to_junit5(code, notes):
    original = code

    replacements = {
        "import org.junit.Test;": "import org.junit.jupiter.api.Test;",
        "import org.junit.Before;": "import org.junit.jupiter.api.BeforeEach;",
        "import org.junit.After;": "import org.junit.jupiter.api.AfterEach;",
        "import static org.junit.Assert.*;": "import static org.junit.jupiter.api.Assertions.*;",
        "import org.junit.Assert;": "import org.junit.jupiter.api.Assertions;"
    }

    for old, new in replacements.items():
        code = code.replace(old, new)

    code = code.replace("@Before\n", "@BeforeEach\n")
    code = code.replace("@After\n", "@AfterEach\n")
    code = code.replace("@Before\r\n", "@BeforeEach\r\n")
    code = code.replace("@After\r\n", "@AfterEach\r\n")

    if code != original:
        notes.append("RepairedJUnit4ToJUnit5")

    return code


def collect_stage1_imports(code):
    imports = []

    # JUnit
    if "@Test" in code:
        imports.append("org.junit.jupiter.api.Test")

    if "@BeforeEach" in code:
        imports.append("org.junit.jupiter.api.BeforeEach")

    if "@AfterEach" in code:
        imports.append("org.junit.jupiter.api.AfterEach")

    if "Assertions." in code:
        imports.append("org.junit.jupiter.api.Assertions")

    # Selenium
    if re.search(r"\bWebDriver\b", code):
        imports.append("org.openqa.selenium.WebDriver")

    if re.search(r"\bChromeDriver\b", code):
        imports.append("org.openqa.selenium.chrome.ChromeDriver")

    if re.search(r"\bBy\.", code):
        imports.append("org.openqa.selenium.By")

    if re.search(r"\bWebElement\b", code):
        imports.append("org.openqa.selenium.WebElement")

    if re.search(r"\bWebDriverWait\b", code):
        imports.append("org.openqa.selenium.support.ui.WebDriverWait")

    if re.search(r"\bExpectedConditions\b", code):
        imports.append("org.openqa.selenium.support.ui.ExpectedConditions")

    if re.search(r"\bDuration\b", code):
        imports.append("java.time.Duration")

    # Selenide
    if "Configuration." in code:
        imports.append("com.codeborne.selenide.Configuration")

    if re.search(r"\bSelenideElement\b", code):
        imports.append("com.codeborne.selenide.SelenideElement")

    if re.search(r"\bElementsCollection\b", code):
        imports.append("com.codeborne.selenide.ElementsCollection")

    if re.search(r"\$[\s]*\(", code) or re.search(r"\$\$[\s]*\(", code):
        imports.append("static com.codeborne.selenide.Selenide.*")

    if re.search(r"(?<![A-Za-z0-9_\\.])open\s*\(", code):
        imports.append("static com.codeborne.selenide.Selenide.open")

    # Broad condition imports are safer for LLM-generated Selenide code
    condition_tokens = [
        "text(",
        "value(",
        "empty",
        "visible",
        "exist",
        "enabled",
        "disabled",
        "appear",
        "disappear",
        "cssClass(",
        "attribute("
    ]

    if any(token in code for token in condition_tokens):
        imports.append("static com.codeborne.selenide.Condition.*")

    collection_condition_tokens = [
        "size(",
        "sizeGreaterThan(",
        "texts(",
        "empty"
    ]

    if any(token in code for token in collection_condition_tokens):
        imports.append("static com.codeborne.selenide.CollectionCondition.*")

    return imports


def apply_stage1_repair(code):
    notes = []

    code, changed = clean_markdown_fences(code)

    if changed:
        notes.append("RemovedMarkdownFences")

    code = repair_junit4_to_junit5(code, notes)

    stage1_imports = collect_stage1_imports(code)
    code = add_imports(code, stage1_imports, notes, "Stage1AddedMissingImports")

    code = ensure_public_class(code, notes)

    code = remove_duplicate_imports(code, notes)

    return code, notes


# ------------------------------------------------------------
# Stage-2 repair rules
# ------------------------------------------------------------

def repair_invalid_selenide_static_imports(code, notes):
    invalid_fragments = [
        "com.codeborne.selenide.WebDriverRunner.webdriverContainer",
        "com.codeborne.selenide.WebDriverRunner.browser",
        "com.codeborne.selenide.WebDriverRunner.title",
        "com.codeborne.selenide.WebDriverRunner.config",
        "com.codeborne.selenide.WebDriverRunner.clearBrowserCookies",
        "com.codeborne.selenide.WebDriverRunner.clearBrowserLocalStorage",
        "com.codeborne.selenide.Configuration.browser",
        "com.codeborne.selenide.Browsers.CHROME",
        "org.mybatis.jpetstore.pages"
    ]

    return remove_import_lines(
        code,
        invalid_fragments,
        notes,
        "Stage2RemovedInvalidImports"
    )


def repair_browser_configuration(code, notes):
    original = code

    code = re.sub(
        r"(?<![A-Za-z0-9_\\.])browser\s*=\s*CHROME\s*;",
        'Configuration.browser = "chrome";',
        code
    )

    code = re.sub(
        r"(?<![A-Za-z0-9_\\.])browser\s*=\s*\"chrome\"\s*;",
        'Configuration.browser = "chrome";',
        code
    )

    code = re.sub(
        r"Configuration\.browser\s*=\s*CHROME\s*;",
        'Configuration.browser = "chrome";',
        code
    )

    code = re.sub(
        r"Configuration\.browser\s*=\s*Browser\.CHROME\s*;",
        'Configuration.browser = "chrome";',
        code
    )

    code = re.sub(
        r"config\s*\(\s*\)\.browser\s*=\s*CHROME\s*;",
        'Configuration.browser = "chrome";',
        code
    )

    code = re.sub(
        r"config\s*\(\s*\)\.browser\s*=\s*\"chrome\"\s*;",
        'Configuration.browser = "chrome";',
        code
    )

    if code != original:
        notes.append("Stage2RepairedBrowserConfiguration")

    return code


def repair_selenide_utility_methods(code, notes):
    imports = []

    if re.search(r"(?<![A-Za-z0-9_\\.])clearBrowserCookies\s*\(", code):
        imports.append("static com.codeborne.selenide.Selenide.clearBrowserCookies")

    if re.search(r"(?<![A-Za-z0-9_\\.])clearBrowserLocalStorage\s*\(", code):
        imports.append("static com.codeborne.selenide.Selenide.clearBrowserLocalStorage")

    if re.search(r"(?<![A-Za-z0-9_\\.])title\s*\(", code):
        imports.append("static com.codeborne.selenide.Selenide.title")

    if imports:
        code = add_imports(code, imports, notes, "Stage2RepairedSelenideUtilityImports")

    return code


def repair_should_have_value(code, notes):
    original = code

    code = re.sub(
        r"\.shouldHaveValue\s*\(([^)]*)\)",
        r".shouldHave(value(\1))",
        code
    )

    if code != original:
        notes.append("Stage2ReplacedShouldHaveValue")

    return code


def repair_first_method(code, notes):
    original = code

    code = re.sub(
        r"\.first\s*\(\s*\)",
        ".get(0)",
        code
    )

    if code != original:
        notes.append("Stage2ReplacedFirstWithGetZero")

    return code


def repair_by_or_usage(code, notes):
    original = code

    code = re.sub(
        r"\.or\s*\(\s*By\.[A-Za-z]+\s*\(\s*\"[^\"]*\"\s*\)\s*\)",
        "",
        code
    )

    if code != original:
        notes.append("Stage2RemovedInvalidByOr")

    return code


def repair_assert_that_usage(code, notes):
    original = code

    code = re.sub(
        r"assertThat\s*\(([^;]+?)\)\.contains\s*\(([^;]+?)\)\s*;",
        r"Assertions.assertTrue(\1.contains(\2));",
        code
    )

    code = re.sub(
        r"assertThat\s*\(([^;]+?)\)\.isEqualTo\s*\(([^;]+?)\)\s*;",
        r"Assertions.assertEquals(\2, \1);",
        code
    )

    code = re.sub(
        r"assertThat\s*\(([^;]+?)\)\.isTrue\s*\(\s*\)\s*;",
        r"Assertions.assertTrue(\1);",
        code
    )

    code = re.sub(
        r"assertThat\s*\(([^;]+?)\)\.isFalse\s*\(\s*\)\s*;",
        r"Assertions.assertFalse(\1);",
        code
    )

    if code != original:
        notes.append("Stage2ReplacedAssertThatWithJUnitAssertions")

    return code


def collect_stage2_imports(code):
    imports = []

    if "Configuration." in code:
        imports.append("com.codeborne.selenide.Configuration")

    if "Assertions." in code:
        imports.append("org.junit.jupiter.api.Assertions")

    if re.search(r"\$[\s]*\(", code) or re.search(r"\$\$[\s]*\(", code):
        imports.append("static com.codeborne.selenide.Selenide.*")

    if any(token in code for token in ["text(", "value(", "empty", "visible", "exist"]):
        imports.append("static com.codeborne.selenide.Condition.*")

    if any(token in code for token in ["size(", "sizeGreaterThan(", "texts("]):
        imports.append("static com.codeborne.selenide.CollectionCondition.*")

    return imports


def final_static_cleanup(code, notes):
    original = code

    code = re.sub(
        r"^\s*CHROME\s*;\s*$",
        "",
        code,
        flags=re.MULTILINE
    )

    if code != original:
        notes.append("Stage2FinalStaticCleanup")

    return code


def apply_stage2_repair(code):
    notes = []

    code = repair_invalid_selenide_static_imports(code, notes)
    code = repair_browser_configuration(code, notes)
    code = repair_selenide_utility_methods(code, notes)
    code = repair_should_have_value(code, notes)
    code = repair_first_method(code, notes)
    code = repair_by_or_usage(code, notes)
    code = repair_assert_that_usage(code, notes)

    stage2_imports = collect_stage2_imports(code)
    code = add_imports(code, stage2_imports, notes, "Stage2AddedMissingImports")

    code = final_static_cleanup(code, notes)
    code = remove_duplicate_imports(code, notes)

    return code, notes


def detect_remaining_static_warnings(code):
    warnings = []

    if len(code.strip()) == 0:
        warnings.append("EmptyCode")

    if code.count("{") != code.count("}"):
        warnings.append("BraceMismatch")

    if "import static com.codeborne.selenide.WebDriverRunner.browser;" in code:
        warnings.append("InvalidBrowserStaticImportRemaining")

    if "import static com.codeborne.selenide.WebDriverRunner.webdriverContainer;" in code:
        warnings.append("InvalidWebDriverContainerImportRemaining")

    if "browser = CHROME" in code:
        warnings.append("BrowserChromeAssignmentRemaining")

    if ".shouldHaveValue(" in code:
        warnings.append("ShouldHaveValueRemaining")

    if ".first()" in code:
        warnings.append("FirstMethodRemaining")

    if ".or(By." in code:
        warnings.append("ByOrRemaining")

    return ";".join(warnings)


# ------------------------------------------------------------
# Maven / javac compile validation
# ------------------------------------------------------------

def get_environment():
    env = os.environ.copy()

    if KNOWN_JAVA_HOME.exists():
        env["JAVA_HOME"] = str(KNOWN_JAVA_HOME)

    if "JAVA_HOME" in env:
        java_bin = Path(env["JAVA_HOME"]) / "bin"
        env["PATH"] = str(java_bin) + os.pathsep + env.get("PATH", "")

    return env


def get_javac_command(env):
    if "JAVA_HOME" in env:
        javac_path = Path(env["JAVA_HOME"]) / "bin" / "javac.exe"

        if javac_path.exists():
            return str(javac_path)

    return "javac"


def get_project_root(project_name):
    project_name = str(project_name).strip()

    if project_name not in PROJECT_ROOTS:
        return None

    project_root = PROJECT_ROOTS[project_name]

    if not project_root.exists():
        return None

    if not (project_root / "pom.xml").exists():
        return None

    return project_root


def get_maven_command(project_root):
    mvnw = project_root / "mvnw.cmd"

    if mvnw.exists():
        return [str(mvnw)]

    return ["mvn"]


def run_command(command, cwd, env, timeout_seconds):
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            shell=False
        )

        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timeout": False
        }

    except subprocess.TimeoutExpired as e:
        return {
            "returncode": -999,
            "stdout": e.stdout if e.stdout else "",
            "stderr": e.stderr if e.stderr else "TIMEOUT",
            "timeout": True
        }

    except Exception as e:
        return {
            "returncode": -998,
            "stdout": "",
            "stderr": str(e),
            "timeout": False
        }


def safe_project_key(project_root):
    text = str(project_root)
    text = text.replace(":", "")
    text = text.replace("\\", "_")
    text = text.replace("/", "_")
    text = text.replace(" ", "_")
    return text


def prepare_project_classpath(project_root, env):
    CLASSPATH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    project_key = safe_project_key(project_root)
    cp_file = CLASSPATH_CACHE_DIR / f"{project_key}_classpath.txt"

    if cp_file.exists():
        cached = read_text_file(cp_file).strip()

        if cached != "":
            return cached, "ClasspathCached"

    maven_cmd = get_maven_command(project_root)

    command = (
        maven_cmd
        + [
            "-q",
            "-DskipTests",
            "compile",
            "dependency:build-classpath",
            f"-Dmdep.outputFile={cp_file}",
            "-Dmdep.includeScope=test"
        ]
    )

    result = run_command(
        command=command,
        cwd=project_root,
        env=env,
        timeout_seconds=300
    )

    if result["returncode"] != 0:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"{project_key}_classpath_failed.log"

        write_text_file(
            log_file,
            "Command: " + " ".join(command)
            + "\n\nReturn code: " + str(result["returncode"])
            + "\n\nSTDOUT:\n" + str(result["stdout"])
            + "\n\nSTDERR:\n" + str(result["stderr"])
        )

        return "", "ClasspathBuildFailed"

    if not cp_file.exists():
        return "", "ClasspathFileMissing"

    classpath_text = read_text_file(cp_file).strip()

    if classpath_text == "":
        return "", "ClasspathEmpty"

    return classpath_text, "ClasspathBuilt"


def build_compile_classpath(project_root, dependency_classpath):
    parts = []

    target_classes = project_root / "target" / "classes"
    target_test_classes = project_root / "target" / "test-classes"

    if target_classes.exists():
        parts.append(str(target_classes))

    if target_test_classes.exists():
        parts.append(str(target_test_classes))

    if dependency_classpath.strip() != "":
        parts.append(dependency_classpath.strip())

    return os.pathsep.join(parts)


def create_temp_source_file(row, repaired_code_path):
    repair_record_id = str(row.get("repair_record_id", "UNKNOWN_REPAIR_ID"))

    code = read_text_file(repaired_code_path)

    class_name = extract_class_name(code)

    if class_name.strip() == "":
        class_name = "Objective1TempTest"

    temp_source = (
        VALIDATION_WORKSPACE
        / repair_record_id
        / "src"
        / f"{class_name}.java"
    )

    write_text_file(temp_source, code)

    return temp_source, class_name


def classify_compile_result(returncode, stdout, stderr, timeout):
    combined = (str(stdout) + "\n" + str(stderr)).lower()

    if timeout:
        return "CompileTimeout"

    if returncode == 0:
        return "CompiledSuccessfully"

    if "class " in combined and " is public, should be declared in a file named" in combined:
        return "JavaFileNameMismatch"

    if "cannot find symbol" in combined:
        return "CannotFindSymbol"

    if "package " in combined and " does not exist" in combined:
        return "PackageDoesNotExist"

    if "method " in combined and "cannot be applied" in combined:
        return "MethodArgumentMismatch"

    if "incompatible types" in combined:
        return "IncompatibleTypes"

    if "illegal start of expression" in combined:
        return "IllegalStartOfExpression"

    if "';' expected" in combined:
        return "MissingSemicolon"

    return "JavacCompilationError"


def extract_first_compile_error(stderr_text):
    lines = str(stderr_text).splitlines()
    blocks = []

    for i, line in enumerate(lines):
        lower = line.lower()

        if (
            ": error:" in lower
            or "cannot find symbol" in lower
            or "package " in lower and " does not exist" in lower
            or "incompatible types" in lower
            or "cannot be applied to given types" in lower
            or "illegal start of expression" in lower
        ):
            start = max(0, i - 2)
            end = min(len(lines), i + 8)
            blocks.append("\n".join(lines[start:end]))

    if blocks:
        return blocks[0]

    return str(stderr_text)[-1500:]


def compile_repaired_file(row, repaired_code_path, env):
    repair_record_id = str(row.get("repair_record_id", "UNKNOWN_REPAIR_ID"))
    project_name = str(row.get("project", "")).strip()

    project_root = get_project_root(project_name)

    if project_root is None:
        return {
            "compile_status": "Skipped",
            "compile_reason": "ProjectRootOrPomMissing",
            "project_root": "",
            "compiled_class_name": "",
            "javac_returncode": "",
            "compile_log_path": "",
            "first_compile_error": ""
        }

    dependency_classpath, cp_status = prepare_project_classpath(project_root, env)

    if dependency_classpath == "":
        return {
            "compile_status": "Skipped",
            "compile_reason": cp_status,
            "project_root": str(project_root),
            "compiled_class_name": "",
            "javac_returncode": "",
            "compile_log_path": "",
            "first_compile_error": ""
        }

    temp_source_file, class_name = create_temp_source_file(row, repaired_code_path)

    output_dir = VALIDATION_WORKSPACE / repair_record_id / "classes"
    output_dir.mkdir(parents=True, exist_ok=True)

    compile_classpath = build_compile_classpath(project_root, dependency_classpath)

    javac_cmd = get_javac_command(env)

    command = [
        javac_cmd,
        "-encoding",
        "UTF-8",
        "-cp",
        compile_classpath,
        "-d",
        str(output_dir),
        str(temp_source_file)
    ]

    result = run_command(
        command=command,
        cwd=project_root,
        env=env,
        timeout_seconds=TIMEOUT_SECONDS
    )

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{repair_record_id}_compile.log"

    first_error = extract_first_compile_error(result["stderr"])

    log_text = []
    log_text.append("Repair Record ID: " + repair_record_id)
    log_text.append("Project Name: " + project_name)
    log_text.append("Project Root: " + str(project_root))
    log_text.append("Repaired Code Path: " + str(repaired_code_path))
    log_text.append("Temporary Source File: " + str(temp_source_file))
    log_text.append("Compiled Class Name: " + class_name)
    log_text.append("Classpath Status: " + cp_status)
    log_text.append("Command: " + " ".join(command))
    log_text.append("\nReturn Code: " + str(result["returncode"]))
    log_text.append("\nSTDOUT:\n" + str(result["stdout"]))
    log_text.append("\nSTDERR:\n" + str(result["stderr"]))

    write_text_file(log_path, "\n".join(log_text))

    compile_reason = classify_compile_result(
        result["returncode"],
        result["stdout"],
        result["stderr"],
        result["timeout"]
    )

    if compile_reason == "CompiledSuccessfully":
        compile_status = "Passed"
    else:
        compile_status = "Failed"

    return {
        "compile_status": compile_status,
        "compile_reason": compile_reason,
        "project_root": str(project_root),
        "compiled_class_name": class_name,
        "javac_returncode": result["returncode"],
        "compile_log_path": str(log_path),
        "first_compile_error": first_error
    }


# ------------------------------------------------------------
# Main repair pipeline
# ------------------------------------------------------------

def get_code_path_from_row(row):
    possible_cols = [
        "original_code_path",
        "generated_test_code_path",
        "code_path",
        "test_code_path"
    ]

    for col in possible_cols:
        if col in row:
            value = row.get(col, "")

            p = resolve_path(value)

            if p is not None and p.exists():
                return p, col

    return None, ""


def save_repaired_file(row, repaired_code):
    repair_record_id = str(row.get("repair_record_id", "UNKNOWN_REPAIR_ID"))
    project = make_safe_text(row.get("project", "UnknownProject"))

    class_name = extract_class_name(repaired_code)

    if class_name.strip() == "":
        class_name = repair_record_id + "_RepairedTest"

    file_name = class_name + ".java"

    repaired_path = REPAIR_DIR / project / repair_record_id / file_name

    write_text_file(repaired_path, repaired_code)

    return repaired_path, class_name


def process_single_row(row, env):
    repair_record_id = str(row.get("repair_record_id", "UNKNOWN_REPAIR_ID"))

    original_path, code_path_column = get_code_path_from_row(row)

    output = row.to_dict()
    output["code_path_column_used"] = code_path_column
    output["original_code_exists"] = "No"
    output["final_repair_status"] = ""
    output["stage1_notes"] = ""
    output["stage2_notes"] = ""
    output["remaining_static_warnings"] = ""
    output["final_repaired_code_path"] = ""
    output["final_repaired_class_name"] = ""

    if original_path is None:
        output["final_repair_status"] = "SkippedOriginalCodeMissing"
        output.update({
            "compile_status": "Skipped",
            "compile_reason": "OriginalCodeMissing",
            "project_root": "",
            "compiled_class_name": "",
            "javac_returncode": "",
            "compile_log_path": "",
            "first_compile_error": ""
        })
        return output

    output["original_code_exists"] = "Yes"

    original_code = read_text_file(original_path)

    if original_code.strip() == "":
        output["final_repair_status"] = "SkippedEmptyOriginalCode"
        output.update({
            "compile_status": "Skipped",
            "compile_reason": "EmptyOriginalCode",
            "project_root": "",
            "compiled_class_name": "",
            "javac_returncode": "",
            "compile_log_path": "",
            "first_compile_error": ""
        })
        return output

    stage1_code, stage1_notes = apply_stage1_repair(original_code)
    stage2_code, stage2_notes = apply_stage2_repair(stage1_code)

    static_warnings = detect_remaining_static_warnings(stage2_code)

    repaired_path, repaired_class_name = save_repaired_file(row, stage2_code)

    output["final_repair_status"] = "RepairedCopyCreated"
    output["stage1_notes"] = ";".join(stage1_notes) if stage1_notes else "NoStage1RuleApplied"
    output["stage2_notes"] = ";".join(stage2_notes) if stage2_notes else "NoStage2RuleApplied"
    output["remaining_static_warnings"] = static_warnings
    output["final_repaired_code_path"] = str(repaired_path)
    output["final_repaired_class_name"] = repaired_class_name

    compile_result = compile_repaired_file(row, repaired_path, env)

    output.update(compile_result)

    return output


def main():
    env = get_environment()

    print("JAVA_HOME:", env.get("JAVA_HOME", "Not set"))
    print("Input file:", INPUT_FILE)
    print("Output file:", OUTPUT_FILE)

    print("\nProject-root mapping check:")
    for project_name, project_root in PROJECT_ROOTS.items():
        pom_status = "YES" if (project_root / "pom.xml").exists() else "NO"
        print(project_name, "->", project_root, "| pom.xml:", pom_status)

    df = read_csv_safely(INPUT_FILE)

    print("\nInput compilation-error rows:", len(df))

    if MAX_ROWS is not None:
        df = df.head(MAX_ROWS).copy()
        print("MAX_ROWS enabled. Rows selected:", len(df))

    output_rows = []

    for idx, row in df.iterrows():
        repair_record_id = str(row.get("repair_record_id", f"ROW_{idx + 1:05d}"))

        print("\nProcessing", len(output_rows) + 1, "of", len(df), ":", repair_record_id)

        output_row = process_single_row(row, env)

        print(
            "Repair:",
            output_row.get("final_repair_status", ""),
            "| Compile:",
            output_row.get("compile_status", ""),
            "-",
            output_row.get("compile_reason", "")
        )

        output_rows.append(output_row)

    output_df = pd.DataFrame(output_rows)
    output_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    print("\nFINAL COMPILATION REPAIR COMPLETED")
    print("=" * 70)
    print("Output file:", OUTPUT_FILE)
    print("Repair directory:", REPAIR_DIR)
    print("Compile logs:", LOG_DIR)

    print("\nFinal repair status:")
    print(output_df["final_repair_status"].value_counts())

    print("\nCompile status:")
    print(output_df["compile_status"].value_counts())

    print("\nCompile reason:")
    print(output_df["compile_reason"].value_counts())

    print("\nProject-wise compile status:")
    if "project" in output_df.columns:
        print(pd.crosstab(output_df["project"], output_df["compile_status"]))

    print("\nStage-1 notes summary:")
    stage1_counter = Counter()

    for notes in output_df["stage1_notes"].fillna(""):
        for note in str(notes).split(";"):
            note = note.strip()
            if note:
                stage1_counter[note] += 1

    for note, count in stage1_counter.most_common(30):
        print(f"{note}: {count}")

    print("\nStage-2 notes summary:")
    stage2_counter = Counter()

    for notes in output_df["stage2_notes"].fillna(""):
        for note in str(notes).split(";"):
            note = note.strip()
            if note:
                stage2_counter[note] += 1

    for note, count in stage2_counter.most_common(30):
        print(f"{note}: {count}")

    print("\nRemaining static warnings:")
    print(output_df["remaining_static_warnings"].value_counts())

    print("\nFirst 10 final results:")
    cols = [
        "repair_record_id",
        "project",
        "workflow_id",
        "model_provider",
        "prompt_type",
        "variant",
        "final_repair_status",
        "compile_status",
        "compile_reason",
        "final_repaired_code_path",
        "compile_log_path"
    ]

    existing_cols = [c for c in cols if c in output_df.columns]

    print(output_df[existing_cols].head(10))

    print("\nDONE")


if __name__ == "__main__":
    main()