# Public Dataset v2

## Dataset title

Dataset for Quality Prediction, Failure Diagnosis, and
Execution-Guided Repair of LLM-Generated Workflow-Based
UI Integration Tests

## Main protocol-aligned corpus

File:
rq1_rq2_protocol_aligned_corpus_2783.csv

Records: 2,783

Successful execution outcomes: 303 (10.89%)

Failure outcomes: 2,480 (89.11%)

The corpus contains records retained under the defined
P1-P3 generation protocol and associated generation
variants used in the final analytical dataset.

## Binary quality prediction

The 2,783-record protocol-aligned corpus is used for
pre-repair binary quality prediction.

## Multiclass failure diagnosis

File:
rq3_failure_diagnosis_final_2352.csv

Records: 2,352

Runtime / Locator Error: 1,171

Compilation Error: 754

Runtime / Driver Error: 427

The final failure-diagnosis corpus excludes records
outside the generation protocol, non-primary or ambiguous
failure categories, post-repair duplicate observations,
and records with unavailable source code and unusable
all-zero static feature vectors.

## Audit records

The audit directory contains:

- the historical 3,069-record aggregate corpus;
- 286 records excluded from the final RQ1/RQ2 protocol;
- 210 records excluded during construction of the final
  multiclass failure-diagnosis dataset;
- a summary of the RQ3 exclusion reasons.

The historical aggregate is included only for
traceability and is not the primary analytical corpus
used for RQ1/RQ2.

## Static prediction features

Fourteen static code-level features are provided:

1. code_char_length
2. code_line_count
3. assertion_count
4. ui_open_count
5. click_count
6. setvalue_count
7. sendkeys_count
8. selector_id_count
9. selector_xpath_count
10. selector_css_count
11. text_assertion_count
12. selenide_usage_count
13. selenium_usage_count
14. junit_usage_count

Execution outcomes, failure labels, project identifiers,
workflow identifiers, model-provider identifiers, and
prompt identifiers were not used as predictive features.

## Sanitization

User-specific local file-system paths are removed from
the public release. Potential common API-key patterns are
also scanned and redacted.

## Version

Public Dataset v2
2026

## Citation

The final DOI-based dataset citation will be added after
repository deposition.

## Reproducibility

Python dependencies are listed in `requirements.txt`.

Final analysis scripts are provided under `scripts/` for:

- RQ1: execution-quality analysis
- RQ2: binary pre-repair quality prediction
- RQ3: multiclass failure diagnosis
- RQ4: execution-guided failure-specific repair

Final reproducible outputs are provided under `results/rq2`, `results/rq3`, and `results/rq4`.

RQ2 and RQ3 use five-fold stratified group cross-validation with grouping by application and workflow to prevent workflow-level leakage.

## Environment

- Python 3.11
- NumPy 2.2.6
- pandas 2.2.3
- scikit-learn 1.9.0
- XGBoost 3.2.0

## Integrity verification

`sha256_manifest.txt` contains SHA-256 checksums for the public package files.
`dataset_manifest.csv` provides dataset-level dimensions and checksums.

## Repair results

RQ4 evaluates execution-guided failure-specific repair under distinct repair settings. These experiments are reported separately and must not be aggregated into a single repair rate.

### Compilation repair

The compilation-repair evaluation contains 802 initially compilation-failing records. After the initial and project-specific repair stages, 378 records were compile-recovered (47.13%), 420 remained unresolved (52.37%), and 4 were skipped (0.50%). Compile recovery indicates that a repaired test became compilable; it does not by itself imply successful runtime execution.

Project-level cumulative compilation recovery was: JPetStore 6, 141/320; BookStore, 112/175; Spring PetClinic, 17/94; and HelpDeskApp, 108/213, with four HelpDeskApp records skipped.

### Project-aware runtime repair

Project-aware runtime-repair subsets are reported independently because they correspond to different failure cohorts and experimental settings. Verified outcomes include BookStore 94/94 passed, JPetStore 6 217/217 passed, HelpDeskApp Runtime/Locator subset 71/71 passed, HelpDeskApp post-compilation subset 107/108 passed, Spring PetClinic project-aware subset 7/7 passed, and the Spring frozen/unknown subset with 3 passed and 3 skipped among 6 evaluated records.

### Strict in-place repair

The BookStore strict in-place experiment evaluated 450 unique records. Stage 1 recovered 301/450 records (66.89%), leaving 149 failures. Stage 2 was applied exactly to those 149 failures and recovered 6 additional records. The final cumulative result was 307/450 passed (68.22%), with 143/450 unresolved (31.78%).

The strict-repair evidence is provided in `strict_inplace_repair_final_450.csv` and `strict_inplace_repair_summary.csv`.

Repair outcomes are not included as additional training observations for RQ2 or RQ3.
