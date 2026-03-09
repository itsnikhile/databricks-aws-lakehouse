# databricks/pipelines/bronze_ingestion.py
"""
Bronze Zone Ingestion Pipeline using Delta Live Tables (DLT)
Ingests raw data from S3 landing zones, Kinesis streams, and CDC sources.
"""

import dlt
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, LongType, TimestampType

# ─── CONFIGURATION ─────────────────────────────────────────────────────────
BRONZE_BUCKET  = spark.conf.get("pipeline.bronze_bucket")
KINESIS_STREAM = spark.conf.get("pipeline.kinesis_stream_name", "")
AWS_REGION     = spark.conf.get("pipeline.aws_region", "us-east-1")

# ─── RAW EVENTS FROM AUTO LOADER (S3) ──────────────────────────────────────
@dlt.table(
    name="raw_events",
    comment="Raw events from S3 landing zone — immutable, append-only",
    table_properties={
        "quality": "bronze",
        "pipelines.reset.allowed": "false",
    },
    partition_cols=["ingest_date"],
)
@dlt.expect_or_drop("valid_event_id", "event_id IS NOT NULL")
@dlt.expect_or_drop("valid_timestamp", "event_timestamp IS NOT NULL")
def raw_events():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.schemaLocation", f"s3://{BRONZE_BUCKET}/_schemas/events")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.maxFilesPerTrigger", 1000)
        .load(f"s3://{BRONZE_BUCKET}/landing/events/")
        .withColumn("ingest_timestamp", F.current_timestamp())
        .withColumn("ingest_date", F.to_date(F.current_timestamp()))
        .withColumn("source_file", F.input_file_name())
    )


# ─── RAW KINESIS STREAM ─────────────────────────────────────────────────────
@dlt.table(
    name="raw_kinesis_stream",
    comment="Real-time events from Amazon Kinesis Data Streams",
    table_properties={"quality": "bronze"},
)
@dlt.expect_or_drop("valid_payload", "data IS NOT NULL")
def raw_kinesis_stream():
    if not KINESIS_STREAM:
        raise ValueError("pipeline.kinesis_stream_name must be set")

    return (
        spark.readStream.format("kinesis")
        .option("streamName", KINESIS_STREAM)
        .option("region", AWS_REGION)
        .option("initialPosition", "TRIM_HORIZON")
        .load()
        .select(
            F.col("partitionKey").alias("partition_key"),
            F.col("sequenceNumber").alias("sequence_number"),
            F.col("approximateArrivalTimestamp").alias("kinesis_timestamp"),
            F.col("data").cast("string").alias("data"),
        )
        .withColumn("ingest_timestamp", F.current_timestamp())
        .withColumn("ingest_date", F.to_date(F.col("kinesis_timestamp")))
    )


# ─── CDC FROM RDS (DMS output on S3) ───────────────────────────────────────
@dlt.table(
    name="raw_cdc_orders",
    comment="Change data capture from RDS orders table via AWS DMS",
    table_properties={"quality": "bronze"},
    partition_cols=["ingest_date"],
)
@dlt.expect_or_drop("valid_operation", "operation IN ('INSERT', 'UPDATE', 'DELETE')")
@dlt.expect_or_drop("valid_order_id", "order_id IS NOT NULL")
def raw_cdc_orders():
    schema = StructType([
        StructField("operation", StringType(), False),
        StructField("order_id", StringType(), False),
        StructField("customer_id", StringType()),
        StructField("product_id", StringType()),
        StructField("quantity", LongType()),
        StructField("unit_price", StringType()),
        StructField("status", StringType()),
        StructField("created_at", TimestampType()),
        StructField("updated_at", TimestampType()),
    ])

    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.schemaLocation", f"s3://{BRONZE_BUCKET}/_schemas/cdc_orders")
        .schema(schema)
        .load(f"s3://{BRONZE_BUCKET}/landing/cdc/orders/")
        .withColumn("ingest_timestamp", F.current_timestamp())
        .withColumn("ingest_date", F.to_date(F.current_timestamp()))
        .withColumn("source_file", F.input_file_name())
    )


# ─── RAW CUSTOMER DATA ──────────────────────────────────────────────────────
@dlt.table(
    name="raw_customers",
    comment="Raw customer data from SaaS CRM via AppFlow batch export",
    table_properties={"quality": "bronze"},
    partition_cols=["ingest_date"],
)
@dlt.expect_or_drop("valid_customer_id", "customer_id IS NOT NULL")
@dlt.expect_or_drop("valid_email_format", "email RLIKE '^[^@]+@[^@]+\\\\.[^@]+$'")
def raw_customers():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", f"s3://{BRONZE_BUCKET}/_schemas/customers")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("header", "true")
        .load(f"s3://{BRONZE_BUCKET}/landing/crm/customers/")
        .withColumn("ingest_timestamp", F.current_timestamp())
        .withColumn("ingest_date", F.to_date(F.current_timestamp()))
        .withColumn("source_file", F.input_file_name())
    )
