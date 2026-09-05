import numpy as np
import pandas as pd

from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.utils.class_weight import compute_sample_weight

from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier

from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix
)

from xgboost import XGBClassifier


# ============================================================
# 1. LOAD FINAL FROZEN RQ3 DATASET
# ============================================================

FILE = r"csv_dataset\objective1_multiclass_final_2352.csv"

df = pd.read_csv(FILE)

print("=" * 70)
print("FINAL RQ3 MULTICLASS DATASET")
print("=" * 70)

print("Shape:", df.shape)

print("\nClass distribution:")
print(df["original_final_label"].value_counts())


# ============================================================
# 2. STATIC FEATURES
# ============================================================

FEATURES = [
    "code_char_length",
    "code_line_count",
    "assertion_count",
    "ui_open_count",
    "click_count",
    "setvalue_count",
    "sendkeys_count",
    "selector_id_count",
    "selector_xpath_count",
    "selector_css_count",
    "text_assertion_count",
    "selenide_usage_count",
    "selenium_usage_count",
    "junit_usage_count"
]

X = df[FEATURES].copy()

for c in FEATURES:
    X[c] = pd.to_numeric(X[c], errors="coerce")


# ============================================================
# 3. LABEL ENCODING
# ============================================================

encoder = LabelEncoder()

y = encoder.fit_transform(
    df["original_final_label"]
)

print("\nEncoded classes:")

for i, c in enumerate(encoder.classes_):
    print(i, "=", c)


# ============================================================
# 4. WORKFLOW GROUPING
# ============================================================

groups = (
    df["project"].astype(str)
    + "::"
    + df["workflow_id"].astype(str)
)

print("\nUnique workflow groups:", groups.nunique())


# ============================================================
# 5. CROSS-VALIDATION
# ============================================================

cv = StratifiedGroupKFold(
    n_splits=5,
    shuffle=True,
    random_state=42
)


# ============================================================
# 6. MODELS
# ============================================================

models = {

    "Logistic Regression":
        Pipeline([
            (
                "imputer",
                SimpleImputer(strategy="median")
            ),
            (
                "scaler",
                StandardScaler()
            ),
            (
                "model",
                LogisticRegression(
                    max_iter=5000,
                    class_weight="balanced",
                    random_state=42
                )
            )
        ]),

    "Decision Tree":
        Pipeline([
            (
                "imputer",
                SimpleImputer(strategy="median")
            ),
            (
                "model",
                DecisionTreeClassifier(
                    class_weight="balanced",
                    random_state=42
                )
            )
        ]),

    "SVM":
        Pipeline([
            (
                "imputer",
                SimpleImputer(strategy="median")
            ),
            (
                "scaler",
                StandardScaler()
            ),
            (
                "model",
                SVC(
                    kernel="rbf",
                    C=1.0,
                    gamma="scale",
                    class_weight="balanced",
                    probability=True,
                    random_state=42
                )
            )
        ]),

    "Random Forest":
        Pipeline([
            (
                "imputer",
                SimpleImputer(strategy="median")
            ),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=500,
                    class_weight="balanced",
                    random_state=42,
                    n_jobs=-1
                )
            )
        ]),

    "XGBoost":
        Pipeline([
            (
                "imputer",
                SimpleImputer(strategy="median")
            ),
            (
                "model",
                XGBClassifier(
                    n_estimators=300,
                    max_depth=4,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    objective="multi:softprob",
                    num_class=3,
                    eval_metric="mlogloss",
                    random_state=42,
                    n_jobs=-1
                )
            )
        ])
}


# ============================================================
# 7. STORAGE
# ============================================================

fold_results = []

oof_predictions = {}


# ============================================================
# 8. TRAINING + FIVE-FOLD EVALUATION
# ============================================================

for model_name, model in models.items():

    print("\n" + "=" * 70)
    print("MODEL:", model_name)
    print("=" * 70)

    oof_pred = np.full(
        len(df),
        -1,
        dtype=int
    )

    for fold, (train_idx, test_idx) in enumerate(
        cv.split(X, y, groups),
        start=1
    ):

        X_train = X.iloc[train_idx]
        X_test = X.iloc[test_idx]

        y_train = y[train_idx]
        y_test = y[test_idx]

        if model_name == "XGBoost":

            sample_weights = compute_sample_weight(
                class_weight="balanced",
                y=y_train
            )

            model.fit(
                X_train,
                y_train,
                model__sample_weight=sample_weights
            )

        else:

            model.fit(
                X_train,
                y_train
            )

        y_pred = model.predict(X_test)

        oof_pred[test_idx] = y_pred

        accuracy = accuracy_score(
            y_test,
            y_pred
        )

        balanced_accuracy = balanced_accuracy_score(
            y_test,
            y_pred
        )

        macro_precision = precision_score(
            y_test,
            y_pred,
            average="macro",
            zero_division=0
        )

        macro_recall = recall_score(
            y_test,
            y_pred,
            average="macro",
            zero_division=0
        )

        macro_f1 = f1_score(
            y_test,
            y_pred,
            average="macro",
            zero_division=0
        )

        weighted_f1 = f1_score(
            y_test,
            y_pred,
            average="weighted",
            zero_division=0
        )

        fold_results.append({
            "Model": model_name,
            "Fold": fold,
            "Accuracy": accuracy,
            "Balanced Accuracy": balanced_accuracy,
            "Macro Precision": macro_precision,
            "Macro Recall": macro_recall,
            "Macro F1": macro_f1,
            "Weighted F1": weighted_f1
        })

        print(
            f"Fold {fold}: "
            f"Accuracy={accuracy:.4f}, "
            f"BA={balanced_accuracy:.4f}, "
            f"Macro-P={macro_precision:.4f}, "
            f"Macro-R={macro_recall:.4f}, "
            f"Macro-F1={macro_f1:.4f}, "
            f"Weighted-F1={weighted_f1:.4f}"
        )

    oof_predictions[model_name] = oof_pred


# ============================================================
# 9. SAVE FOLD RESULTS
# ============================================================

fold_df = pd.DataFrame(fold_results)

fold_output = (
    r"csv_dataset\objective1_multiclass_final_2352_fold_metrics.csv"
)

fold_df.to_csv(
    fold_output,
    index=False
)


# ============================================================
# 10. MEAN ± STANDARD DEVIATION
# ============================================================

metrics = [
    "Accuracy",
    "Balanced Accuracy",
    "Macro Precision",
    "Macro Recall",
    "Macro F1",
    "Weighted F1"
]

summary_rows = []

print("\n")
print("=" * 90)
print("FINAL MULTICLASS RESULTS: MEAN ± SD")
print("=" * 90)

for model_name in models.keys():

    temp = fold_df[
        fold_df["Model"] == model_name
    ]

    row = {
        "Model": model_name
    }

    print("\n" + model_name)

    for metric in metrics:

        mean = temp[metric].mean()
        sd = temp[metric].std(ddof=1)

        row[f"{metric} Mean"] = mean
        row[f"{metric} SD"] = sd

        print(
            f"{metric:20s}: "
            f"{mean:.4f} ± {sd:.4f}"
        )

    summary_rows.append(row)


summary_df = pd.DataFrame(
    summary_rows
)

summary_output = (
    r"csv_dataset\objective1_multiclass_final_2352_summary.csv"
)

summary_df.to_csv(
    summary_output,
    index=False
)


# ============================================================
# 11. FIND BEST MODEL USING MACRO-F1
# ============================================================

best_index = summary_df[
    "Macro F1 Mean"
].idxmax()

best_model = summary_df.loc[
    best_index,
    "Model"
]

print("\n" + "=" * 70)
print("BEST MODEL BY MEAN MACRO-F1:", best_model)
print("=" * 70)


# ============================================================
# 12. OOF CONFUSION MATRIX FOR BEST MODEL
# ============================================================

best_pred = oof_predictions[
    best_model
]

cm = confusion_matrix(
    y,
    best_pred
)

print("\nOOF CONFUSION MATRIX")
print(
    "Rows = Actual classes, "
    "Columns = Predicted classes"
)

print("\nClass order:")

for i, c in enumerate(encoder.classes_):
    print(i, "=", c)

print("\n", cm)


# ============================================================
# 13. SAVE OOF PREDICTIONS
# ============================================================

oof_df = pd.DataFrame({
    "record_id": df["record_id"],
    "project": df["project"],
    "workflow_id": df["workflow_id"],
    "true_label": encoder.inverse_transform(y),
    "predicted_label":
        encoder.inverse_transform(best_pred)
})

oof_output = (
    r"csv_dataset\objective1_multiclass_final_2352_best_model_oof.csv"
)

oof_df.to_csv(
    oof_output,
    index=False
)


# ============================================================
# 14. FINAL FILES
# ============================================================

print("\n" + "=" * 70)
print("FILES CREATED")
print("=" * 70)

print(fold_output)
print(summary_output)
print(oof_output)