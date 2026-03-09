# mlflow/train_churn_model.py
"""
Customer Churn Prediction Model — training script with MLflow tracking.
Reads features from Gold layer, trains a gradient boosted tree classifier,
logs to MLflow, and registers to Model Registry.
"""

import mlflow
import mlflow.sklearn
import pandas as pd
import numpy as np
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import (
    roc_auc_score, f1_score, precision_score,
    recall_score, classification_report
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.impute import SimpleImputer

# ─── CONFIG ─────────────────────────────────────────────────────────────────
CATALOG         = "gold_catalog"
SCHEMA          = "features"
FEATURES_TABLE  = f"{CATALOG}.{SCHEMA}.gold_ml_customer_features"
EXPERIMENT_NAME = "/Shared/churn_prediction"
MODEL_NAME      = "customer_churn_classifier"
TARGET_COL      = "is_churned"

FEATURE_COLS = [
    "total_orders", "total_revenue", "avg_order_value",
    "completed_orders", "total_events", "total_sessions",
    "purchase_events", "days_since_last_order", "customer_age",
    "account_age_days", "purchase_conversion_rate",
]
CATEGORICAL_COLS = ["customer_country", "customer_segment"]

spark = SparkSession.builder.getOrCreate()
mlflow.set_experiment(EXPERIMENT_NAME)


def load_features() -> pd.DataFrame:
    """Load feature table from Gold zone."""
    print(f"Loading features from {FEATURES_TABLE}")
    df = spark.table(FEATURES_TABLE).dropna(subset=[TARGET_COL])
    print(f"  Loaded {df.count():,} rows")
    return df.toPandas()


def preprocess(df: pd.DataFrame):
    """Encode categoricals, impute, and split."""
    # Label encode categoricals
    for col in CATEGORICAL_COLS:
        le = LabelEncoder()
        df[col + "_enc"] = le.fit_transform(df[col].fillna("Unknown"))

    enc_cat_cols = [c + "_enc" for c in CATEGORICAL_COLS]
    all_features = FEATURE_COLS + enc_cat_cols

    X = df[all_features].copy()
    y = df[TARGET_COL].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    class_balance = y.value_counts(normalize=True).to_dict()
    print(f"  Class balance: {class_balance}")

    return X_train, X_test, y_train, y_test, all_features


def build_pipeline(n_estimators=200, max_depth=5, learning_rate=0.05) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("classifier", GradientBoostingClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=0.8,
            min_samples_split=20,
            random_state=42,
        ))
    ])


def evaluate(pipeline, X_test, y_test):
    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]

    return {
        "roc_auc":   roc_auc_score(y_test, y_prob),
        "f1":        f1_score(y_test, y_pred),
        "precision": precision_score(y_test, y_pred),
        "recall":    recall_score(y_test, y_pred),
    }


def log_feature_importance(pipeline, feature_names):
    clf = pipeline.named_steps["classifier"]
    importances = clf.feature_importances_
    fi_df = pd.DataFrame({
        "feature": feature_names,
        "importance": importances
    }).sort_values("importance", ascending=False)

    # Log as artifact
    fi_path = "/tmp/feature_importance.csv"
    fi_df.to_csv(fi_path, index=False)
    mlflow.log_artifact(fi_path, "feature_importance")

    # Log top features as metrics
    for _, row in fi_df.head(10).iterrows():
        mlflow.log_metric(f"fi_{row['feature']}", round(row['importance'], 4))


def train_and_register():
    df = load_features()
    X_train, X_test, y_train, y_test, feature_names = preprocess(df)

    params = {
        "n_estimators":  200,
        "max_depth":     5,
        "learning_rate": 0.05,
    }

    with mlflow.start_run(run_name="churn_gbt_v1") as run:
        mlflow.log_params(params)
        mlflow.log_param("training_rows", len(X_train))
        mlflow.log_param("test_rows", len(X_test))
        mlflow.log_param("features", feature_names)

        # Train
        pipeline = build_pipeline(**params)
        pipeline.fit(X_train, y_train)

        # Cross-validation score
        cv_scores = cross_val_score(pipeline, X_train, y_train, cv=5, scoring="roc_auc")
        mlflow.log_metric("cv_roc_auc_mean", cv_scores.mean())
        mlflow.log_metric("cv_roc_auc_std", cv_scores.std())

        # Evaluate on held-out test set
        metrics = evaluate(pipeline, X_test, y_test)
        mlflow.log_metrics(metrics)

        print("\n=== Model Evaluation ===")
        for k, v in metrics.items():
            print(f"  {k}: {v:.4f}")

        # Log feature importance
        log_feature_importance(pipeline, feature_names)

        # Log model with signature
        from mlflow.models.signature import infer_signature
        signature = infer_signature(X_train, pipeline.predict(X_train))
        mlflow.sklearn.log_model(
            pipeline,
            artifact_path="model",
            signature=signature,
            registered_model_name=MODEL_NAME,
        )

        print(f"\nRun ID: {run.info.run_id}")
        print(f"Model registered as: {MODEL_NAME}")

        # Transition to Staging if AUC > 0.80
        if metrics["roc_auc"] > 0.80:
            client = mlflow.tracking.MlflowClient()
            mv = client.get_latest_versions(MODEL_NAME, stages=["None"])[0]
            client.transition_model_version_stage(
                name=MODEL_NAME,
                version=mv.version,
                stage="Staging",
                archive_existing_versions=False,
            )
            print(f"Model v{mv.version} transitioned to Staging")

    return run.info.run_id


if __name__ == "__main__":
    run_id = train_and_register()
    print(f"\nTraining complete. MLflow run ID: {run_id}")
