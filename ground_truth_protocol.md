\# Ground-Truth Construction Protocol



\## 1. Binary Execution-Quality Ground Truth



Ground truth for RQ1 and RQ2 was derived from actual pre-repair compilation and execution outcomes.



\- Successful execution outcome: the generated test compiled and executed successfully.

\- Failure outcome: the generated test failed because of compilation, runtime/locator, runtime/driver, or other execution-related problems.



The final protocol-aligned binary dataset contains:



\- Total records: 2,783

\- Successful execution outcomes: 303

\- Failures: 2,480



Successful execution indicates execution quality only and does not necessarily imply complete semantic correctness or fault-detection effectiveness.



\## 2. Multiclass Failure-Diagnosis Ground Truth



Ground-truth failure categories for RQ3 were derived from compiler messages, runtime logs, exceptions, and predefined diagnostic rules.



The final multiclass dataset contains 2,352 failed tests classified into:



\- Compilation Error: 754

\- Runtime / Driver Error: 427

\- Runtime / Locator Error: 1,171



Ambiguous, non-primary, post-repair duplicate, out-of-protocol, or unusable records were excluded rather than being forced into an incorrect failure category.



\## 3. Repair Ground Truth



Ground truth for RQ4 was derived from actual recompilation and/or re-execution after applying the corresponding repair procedure.



Repair outcomes were recorded according to the repair setting:



\- Compile-Recovered: the identified compilation failure was removed and the repaired test compiled successfully.

\- Repair-Recovered: the repaired test successfully completed the required runtime validation.

\- Unresolved: the failure remained after the permitted bounded repair procedure.

\- Unsupported: no defensible repair could be established from available compiler, runtime, or application evidence.



Compilation recovery was not automatically treated as runtime success.



\## 4. Leakage Prevention



Execution outcomes, failure labels, project identifiers, workflow identifiers, model-provider identifiers, prompt identifiers, and post-repair outcomes were retained for traceability and evaluation but were not used as predictive input features.



Only predefined static source-code features were supplied to the machine-learning models.

