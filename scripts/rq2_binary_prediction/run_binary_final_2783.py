from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier

from sklearn.metrics import (
    balanced_accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    average_precision_score,
    confusion_matrix
)

from xgboost import XGBClassifier


# ============================================================
# 1. PATHS
# ============================================================

DATASET_ROOT = Path(__file__).resolve().parents[2]

DATA_FILE = (
    DATASET_ROOT /
    "rq1_rq2_protocol_aligned_corpus_2783.csv"
)

OUTPUT_DIR = (
    DATASET_ROOT /
    "results" /
    "rq2"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# 2. LOAD FINAL FROZEN DATASET
# ============================================================

df = pd.read_csv(
    DATA_FILE,
    low_memory=False
)

print("=" * 75)
print("RQ2 - BINARY QUALITY PREDICTION")
print("=" * 75)

print("Dataset:", DATA_FILE)
print("Shape:", df.shape)


# ============================================================
# 3. VERIFY FINAL DATASET
# ============================================================

assert len(df) == 2783

success_count = int(
    (df["binary_label_name"] == "Success").sum()
)

failure_count = int(
    (df["binary_label_name"] == "Failure").sum()
)

assert success_count == 303
assert failure_count == 2480

print("Success:", success_count)
print("Failure:", failure_count)
print(
    "Success rate:",
    f"{success_count / len(df) * 100:.2f}%"
)


# ============================================================
# 4. STATIC FEATURES
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

for feature in FEATURES:
    X[feature] = pd.to_numeric(
        X[feature],
        errors="coerce"
    )


# ============================================================
# 5. TARGET
#
# Failure = 0
# Success = 1
# ============================================================

y = (
    df["binary_label_name"]
    .eq("Success")
    .astype(int)
    .to_numpy()
)


# ============================================================
# 6. WORKFLOW GROUPING
# ============================================================

groups = (
    df["project"].astype(str)
    + "::"
    + df["workflow_id"].astype(str)
)

print(
    "Unique workflow groups:",
    groups.nunique()
)


# ============================================================
# 7. FIVE-FOLD WORKFLOW-GROUPED CROSS-VALIDATION
# ============================================================

cv = StratifiedGroupKFold(
    n_splits=5,
    shuffle=True,
    random_state=42
)

splits = list(
    cv.split(
        X,
        y,
        groups
    )
)


# ============================================================
# 8. CLASS IMBALANCE
# ============================================================

scale_pos_weight = (
    failure_count /
    success_count
)

print(
    "XGBoost scale_pos_weight:",
    f"{scale_pos_weight:.6f}"
)


# ============================================================
# 9. MODELS
# ============================================================

models = {

    "Logistic Regression":
        Pipeline([
            (
                "imputer",
                SimpleImputer(
                    strategy="median"
                )
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
                    solver="liblinear",
                    random_state=42
                )
            )
        ]),

    "Decision Tree":
        Pipeline([
            (
                "imputer",
                SimpleImputer(
                    strategy="median"
                )
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
                SimpleImputer(
                    strategy="median"
                )
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
                SimpleImputer(
                    strategy="median"
                )
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
                SimpleImputer(
                    strategy="median"
                )
            ),
            (
                "model",
                XGBClassifier(
                    n_estimators=300,
                    max_depth=4,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    objective="binary:logistic",
                    eval_metric="logloss",
                    scale_pos_weight=scale_pos_weight,
                    random_state=42,
                    n_jobs=-1
                )
            )
        ])
}


# ============================================================
# 10. STORAGE
# ============================================================

fold_results = []

all_oof_predictions = {}


# ============================================================
# 11. TRAIN AND EVALUATE
# ============================================================

for model_name, model in models.items():

    print("\n" + "=" * 75)
    print("MODEL:", model_name)
    print("=" * 75)

    oof_probability = np.zeros(
        len(df),
        dtype=float
    )

    oof_prediction = np.zeros(
        len(df),
        dtype=int
    )

    for fold, (train_idx, test_idx) in enumerate(
        splits,
        start=1
    ):

        X_train = X.iloc[train_idx]
        X_test = X.iloc[test_idx]

        y_train = y[train_idx]
        y_test = y[test_idx]

        model.fit(
            X_train,
            y_train
        )

        probability = (
            model.predict_proba(
                X_test
            )[:, 1]
        )

        prediction = model.predict(X_test).astype(int)

        oof_probability[
            test_idx
        ] = probability

        oof_prediction[
            test_idx
        ] = prediction

        balanced_accuracy = (
            balanced_accuracy_score(
                y_test,
                prediction
            )
        )

        precision = precision_score(
            y_test,
            prediction,
            zero_division=0
        )

        recall = recall_score(
            y_test,
            prediction,
            zero_division=0
        )

        f1 = f1_score(
            y_test,
            prediction,
            zero_division=0
        )

        roc_auc = roc_auc_score(
            y_test,
            probability
        )

        pr_auc = average_precision_score(
            y_test,
            probability
        )

        fold_results.append({
            "Model": model_name,
            "Fold": fold,
            "Balanced Accuracy":
                balanced_accuracy,
            "Precision":
                precision,
            "Recall":
                recall,
            "F1":
                f1,
            "ROC-AUC":
                roc_auc,
            "PR-AUC":
                pr_auc
        })

        print(
            f"Fold {fold}: "
            f"BA={balanced_accuracy:.4f}, "
            f"Precision={precision:.4f}, "
            f"Recall={recall:.4f}, "
            f"F1={f1:.4f}, "
            f"ROC-AUC={roc_auc:.4f}, "
            f"PR-AUC={pr_auc:.4f}"
        )

    all_oof_predictions[
        model_name
    ] = {
        "prediction":
            oof_prediction,

        "probability":
            oof_probability
    }


# ============================================================
# 12. SAVE FOLD METRICS
# ============================================================

fold_df = pd.DataFrame(
    fold_results
)

fold_file = (
    OUTPUT_DIR /
    "binary_all_models_fold_metrics.csv"
)

fold_df.to_csv(
    fold_file,
    index=False
)


# ============================================================
# 13. MEAN +/- STANDARD DEVIATION
# ============================================================

METRICS = [
    "Balanced Accuracy",
    "Precision",
    "Recall",
    "F1",
    "ROC-AUC",
    "PR-AUC"
]

summary_rows = []

print("\n")
print("=" * 90)
print("RQ2 FINAL RESULTS: MEAN +/- SD")
print("=" * 90)

for model_name in models.keys():

    model_folds = fold_df[
        fold_df["Model"]
        == model_name
    ]

    summary = {
        "Model":
            model_name
    }

    print(
        "\n",
        model_name
    )

    for metric in METRICS:

        mean_value = (
            model_folds[
                metric
            ].mean()
        )

        sd_value = (
            model_folds[
                metric
            ].std(
                ddof=1
            )
        )

        summary[
            f"{metric} Mean"
        ] = mean_value

        summary[
            f"{metric} SD"
        ] = sd_value

        print(
            f"{metric:20s}: "
            f"{mean_value:.4f} "
            f"+/- {sd_value:.4f}"
        )

    summary_rows.append(
        summary
    )

summary_df = pd.DataFrame(
    summary_rows
)

summary_file = (
    OUTPUT_DIR /
    "binary_all_models_summary.csv"
)

summary_df.to_csv(
    summary_file,
    index=False
)


# ============================================================
# 14. SAVE OOF PREDICTIONS FOR EACH MODEL
# ============================================================

safe_names = {
    "Logistic Regression":
        "logistic_regression",

    "Decision Tree":
        "decision_tree",

    "SVM":
        "svm",

    "Random Forest":
        "random_forest",

    "XGBoost":
        "xgboost"
}

for model_name in models.keys():

    prediction = (
        all_oof_predictions[
            model_name
        ]["prediction"]
    )

    probability = (
        all_oof_predictions[
            model_name
        ]["probability"]
    )

    oof_df = pd.DataFrame({

        "record_id":
            df["record_id"],

        "project":
            df["project"],

        "workflow_id":
            df["workflow_id"],

        "y_true":
            y,

        "y_pred":
            prediction,

        "success_probability":
            probability
    })

    filename = (
        OUTPUT_DIR /
        (
            "binary_"
            + safe_names[model_name]
            + "_oof_predictions.csv"
        )
    )

    oof_df.to_csv(
        filename,
        index=False
    )


# ============================================================
# 15. POOLED OOF PERFORMANCE
# ============================================================

pooled_rows = []

print("\n")
print("=" * 90)
print("POOLED OUT-OF-FOLD RESULTS")
print("=" * 90)

for model_name in models.keys():

    prediction = (
        all_oof_predictions[
            model_name
        ]["prediction"]
    )

    probability = (
        all_oof_predictions[
            model_name
        ]["probability"]
    )

    row = {

        "Model":
            model_name,

        "Balanced Accuracy":
            balanced_accuracy_score(
                y,
                prediction
            ),

        "Precision":
            precision_score(
                y,
                prediction,
                zero_division=0
            ),

        "Recall":
            recall_score(
                y,
                prediction,
                zero_division=0
            ),

        "F1":
            f1_score(
                y,
                prediction,
                zero_division=0
            ),

        "ROC-AUC":
            roc_auc_score(
                y,
                probability
            ),

        "OOF AP":
            average_precision_score(
                y,
                probability
            )
    }

    pooled_rows.append(
        row
    )

    print(
        f"\n{model_name}"
    )

    for key, value in row.items():

        if key != "Model":
            print(
                f"{key:20s}: "
                f"{value:.4f}"
            )


pooled_df = pd.DataFrame(
    pooled_rows
)

pooled_file = (
    OUTPUT_DIR /
    "binary_all_models_pooled_oof_metrics.csv"
)

pooled_df.to_csv(
    pooled_file,
    index=False
)


# ============================================================
# 16. SVM POOLED OOF CONFUSION MATRIX
# ============================================================

svm_prediction = (
    all_oof_predictions[
        "SVM"
    ]["prediction"]
)

svm_cm = confusion_matrix(
    y,
    svm_prediction,
    labels=[0, 1]
)

print("\n")
print("=" * 75)
print("SVM POOLED OOF CONFUSION MATRIX")
print("=" * 75)

print(
    "Rows = Actual [Failure, Success]"
)

print(
    "Columns = Predicted [Failure, Success]"
)

print(
    svm_cm
)

cm_df = pd.DataFrame(
    svm_cm,
    index=[
        "Actual Failure",
        "Actual Success"
    ],
    columns=[
        "Predicted Failure",
        "Predicted Success"
    ]
)

cm_df.to_csv(
    OUTPUT_DIR /
    "binary_svm_oof_confusion_matrix.csv"
)


# ============================================================
# 17. FINAL FILE LIST
# ============================================================

print("\n")
print("=" * 75)
print("FILES CREATED")
print("=" * 75)

for file in sorted(
    OUTPUT_DIR.glob("*.csv")
):
    print(
        file.name
    )

print("\nRQ2 COMPLETE.")