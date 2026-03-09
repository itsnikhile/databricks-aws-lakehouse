# databricks/pipelines/silver_transformations.py
"""
Silver Zone Transformation Pipeline using Delta Live Tables (DLT)
Cleans, validates, deduplicates, and conforms data from the Bronze zone.
Applies SCD Type 2 for slowly changing dimensions.
"""

import dlt
from pyspark.sql import functions as F, Window


# ─── SILVER EVENTS ──────────────────────────────────────────────────────────
@dlt.table(
    name="silver_events",
    comment="Cleaned, deduplicated, and type-cast events",
    table_properties={
        "quality": "silver",
        "delta.enableChangeDataFeed": "true",
    },
    partition_cols=["event_date"],
)
@dlt.expect_or_warn("positive_value", "event_value >= 0")
@dlt.expect_or_drop("valid_event_type", "event_type IN ('click', 'view', 'purchase', 'search', 'error')")
def silver_events():
    return (
        dlt.read_stream("raw_events")
        # Parse and cast
        .withColumn("event_timestamp", F.to_timestamp("event_timestamp"))
        .withColumn("event_value", F.col("event_value").cast("double"))
        .withColumn("session_duration_seconds", F.col("session_duration_seconds").cast("int"))
        .withColumn("event_date", F.to_date("event_timestamp"))
        # Enrich
        .withColumn("event_hour", F.hour("event_timestamp"))
        .withColumn("is_weekend", F.dayofweek("event_timestamp").isin([1, 7]))
        # Dedup by event_id (keep latest)
        .dropDuplicates(["event_id"])
        # Drop internal columns
        .drop("source_file", "ingest_timestamp")
    )


# ─── SILVER ORDERS (SCD Type 2 via APPLY CHANGES) ──────────────────────────
dlt.create_streaming_table(
    name="silver_orders",
    comment="Orders with full history via SCD Type 2 — tracks all changes",
    table_properties={
        "quality": "silver",
        "delta.enableChangeDataFeed": "true",
    },
    partition_cols=["order_date"],
)

dlt.apply_changes(
    target="silver_orders",
    source="raw_cdc_orders",
    keys=["order_id"],
    sequence_by=F.col("updated_at"),
    apply_as_deletes=F.expr("operation = 'DELETE'"),
    apply_as_truncates=F.expr("operation = 'TRUNCATE'"),
    column_list=["order_id", "customer_id", "product_id", "quantity",
                 "unit_price", "status", "created_at", "updated_at"],
    stored_as_scd_type=2,
)


# ─── SILVER CUSTOMERS (deduplicated + PII masked) ───────────────────────────
@dlt.table(
    name="silver_customers",
    comment="Cleaned customer master data with PII masked for analysts",
    table_properties={
        "quality": "silver",
        "delta.enableChangeDataFeed": "true",
    },
)
@dlt.expect_or_drop("valid_customer_id", "customer_id IS NOT NULL")
@dlt.expect_or_warn("valid_country", "country IS NOT NULL")
def silver_customers():
    # Window for dedup — keep most recent record per customer
    w = Window.partitionBy("customer_id").orderBy(F.col("ingest_timestamp").desc())

    return (
        dlt.read("raw_customers")
        .withColumn("rank", F.row_number().over(w))
        .filter(F.col("rank") == 1)
        .drop("rank")
        # Type casting
        .withColumn("signup_date", F.to_date("signup_date"))
        .withColumn("age", F.col("age").cast("int"))
        .withColumn("lifetime_value", F.col("lifetime_value").cast("double"))
        # PII masking for downstream analysts
        .withColumn("email_masked", F.regexp_replace("email", r"^(.{2}).*(@.*)", r"$1***$2"))
        .withColumn("phone_masked", F.regexp_replace("phone", r"\d{6}(\d{4})", r"XXXXXX$1"))
        # Drop raw PII — actual PII stays in bronze for authorized access
        .drop("email", "phone", "ssn", "date_of_birth")
        .withColumn("processed_timestamp", F.current_timestamp())
    )


# ─── SILVER KINESIS EVENTS (parsed from JSON payload) ───────────────────────
@dlt.table(
    name="silver_stream_events",
    comment="Parsed and structured real-time events from Kinesis",
    table_properties={"quality": "silver"},
    partition_cols=["event_date"],
)
@dlt.expect_or_drop("valid_payload", "user_id IS NOT NULL AND action IS NOT NULL")
def silver_stream_events():
    schema = "user_id STRING, action STRING, properties MAP<STRING,STRING>, ts BIGINT"

    return (
        dlt.read_stream("raw_kinesis_stream")
        .withColumn("payload", F.from_json(F.col("data"), schema))
        .select(
            "partition_key",
            "sequence_number",
            "kinesis_timestamp",
            F.col("payload.user_id").alias("user_id"),
            F.col("payload.action").alias("action"),
            F.col("payload.properties").alias("properties"),
            F.col("payload.ts").alias("client_timestamp_ms"),
        )
        .withColumn("event_date", F.to_date("kinesis_timestamp"))
        .withColumn("latency_ms",
            (F.unix_timestamp("kinesis_timestamp") * 1000 - F.col("client_timestamp_ms"))
        )
    )
