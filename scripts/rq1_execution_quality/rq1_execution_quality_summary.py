import pandas as pd

FILE = r"..\..\rq1_rq2_protocol_aligned_corpus_2783.csv"

df = pd.read_csv(FILE)

print("=" * 60)
print("RQ1 - INITIAL EXECUTION QUALITY")
print("=" * 60)

print("Total tests:", len(df))

counts = df["binary_label_name"].value_counts()

success = int(counts.get("Success", 0))
failure = int(counts.get("Failure", 0))

print("Success:", success)
print("Failure:", failure)

print(
    "Success rate:",
    f"{success / len(df) * 100:.2f}%"
)

print(
    "Failure rate:",
    f"{failure / len(df) * 100:.2f}%"
)

print("\nDetailed execution labels:")
print(
    df["original_final_label"]
    .value_counts()
    .to_string()
)

assert len(df) == 2783
assert success == 303
assert failure == 2480

print("\nRQ1 COUNTS VERIFIED.")