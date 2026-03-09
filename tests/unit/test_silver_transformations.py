# tests/unit/test_silver_transformations.py
"""
Unit tests for Silver transformation logic.
Uses a local Spark session with Delta Lake support.
"""

import pytest
from datetime import datetime, timedelta
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import *


@pytest.fixture(scope="session")
def spark():
    return (
        SparkSession.builder
        .master("local[2]")
        .appName("unit-tests")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )


class TestSilverEventsTransformation:

    def test_event_timestamp_cast(self, spark):
        """Test that event_timestamp is correctly cast to TimestampType."""
        data = [("evt_001", "click", "2024-01-15 10:30:00", "user_A", 1.5)]
        schema = StructType([
            StructField("event_id", StringType()),
            StructField("event_type", StringType()),
            StructField("event_timestamp", StringType()),
            StructField("customer_id", StringType()),
            StructField("event_value", StringType()),
        ])

        df = spark.createDataFrame(data, schema)
        result = df.withColumn("event_timestamp", F.to_timestamp("event_timestamp"))

        assert result.schema["event_timestamp"].dataType == TimestampType()
        assert result.count() == 1

    def test_deduplication_keeps_single_record(self, spark):
        """Test that deduplication via dropDuplicates keeps one record per event_id."""
        data = [
            ("evt_001", "click", "2024-01-15 10:30:00"),
            ("evt_001", "click", "2024-01-15 10:30:01"),  # duplicate
            ("evt_002", "view",  "2024-01-15 10:31:00"),
        ]
        schema = ["event_id", "event_type", "event_timestamp"]
        df = spark.createDataFrame(data, schema)

        result = df.dropDuplicates(["event_id"])
        assert result.count() == 2

    def test_pii_email_masking(self, spark):
        """Test that email masking replaces middle characters correctly."""
        data = [("cust_001", "john.doe@example.com", "+1-555-123-4567")]
        schema = ["customer_id", "email", "phone"]
        df = spark.createDataFrame(data, schema)

        result = (
            df
            .withColumn("email_masked", F.regexp_replace("email", r"^(.{2}).*(@.*)", r"$1***$2"))
            .withColumn("phone_masked", F.regexp_replace("phone", r"\d{6}(\d{4})", r"XXXXXX$1"))
        )

        row = result.collect()[0]
        assert row["email_masked"].startswith("jo***")
        assert "@example.com" in row["email_masked"]
        assert "XXXXXX" in row["phone_masked"]
        assert row.asDict().get("email") is not None  # original still present before drop

    def test_invalid_event_types_filtered(self, spark):
        """Test that invalid event types are filtered out by DLT Expectation equivalent."""
        valid_types = {"click", "view", "purchase", "search", "error"}
        data = [
            ("evt_001", "click"),
            ("evt_002", "view"),
            ("evt_003", "invalid_type"),  # should be filtered
            ("evt_004", "unknown"),        # should be filtered
            ("evt_005", "purchase"),
        ]
        schema = ["event_id", "event_type"]
        df = spark.createDataFrame(data, schema)

        result = df.filter(F.col("event_type").isin(list(valid_types)))
        assert result.count() == 3

    def test_event_date_extraction(self, spark):
        """Test that event_date is correctly extracted from event_timestamp."""
        data = [("evt_001", "2024-03-15 23:59:59")]
        schema = ["event_id", "event_timestamp"]
        df = spark.createDataFrame(data, schema)

        result = (
            df
            .withColumn("event_timestamp", F.to_timestamp("event_timestamp"))
            .withColumn("event_date", F.to_date("event_timestamp"))
        )

        row = result.collect()[0]
        assert str(row["event_date"]) == "2024-03-15"


class TestGoldAggregations:

    def test_daily_revenue_calculation(self, spark):
        """Test that daily revenue is correctly summed."""
        data = [
            ("ord_001", "cust_A", 2, "50.00", "completed", "2024-01-15"),
            ("ord_002", "cust_B", 1, "75.00", "completed", "2024-01-15"),
            ("ord_003", "cust_C", 3, "25.00", "refunded",  "2024-01-15"),
            ("ord_004", "cust_A", 1, "100.00", "completed", "2024-01-16"),
        ]
        schema = ["order_id", "customer_id", "quantity", "unit_price", "status", "order_date"]
        df = spark.createDataFrame(data, schema)

        result = (
            df
            .withColumn("revenue", F.col("quantity") * F.col("unit_price").cast("double"))
            .groupBy("order_date")
            .agg(F.sum("revenue").alias("total_revenue"), F.count("order_id").alias("total_orders"))
        )

        rows = {r["order_date"]: r for r in result.collect()}
        assert rows["2024-01-15"]["total_revenue"] == pytest.approx(250.0)
        assert rows["2024-01-15"]["total_orders"] == 3
        assert rows["2024-01-16"]["total_revenue"] == pytest.approx(100.0)

    def test_customer_segment_classification(self, spark):
        """Test customer segment assignment logic."""
        data = [
            ("cust_A", 15000.0),  # VIP
            ("cust_B", 5000.0),   # High Value
            ("cust_C", 500.0),    # Regular
            ("cust_D", 10.0),     # Occasional
        ]
        schema = ["customer_id", "total_revenue"]
        df = spark.createDataFrame(data, schema)

        result = df.withColumn(
            "customer_segment",
            F.when(F.col("total_revenue") >= 10000, "VIP")
            .when(F.col("total_revenue") >= 1000, "High Value")
            .when(F.col("total_revenue") >= 100, "Regular")
            .otherwise("Occasional")
        )

        segments = {r["customer_id"]: r["customer_segment"] for r in result.collect()}
        assert segments["cust_A"] == "VIP"
        assert segments["cust_B"] == "High Value"
        assert segments["cust_C"] == "Regular"
        assert segments["cust_D"] == "Occasional"

    def test_churn_flag_days_since_order(self, spark):
        """Test that churn is flagged for customers with no orders in 90+ days."""
        today = datetime.today().date()
        data = [
            ("cust_A", str(today - timedelta(days=30))),   # active
            ("cust_B", str(today - timedelta(days=91))),   # churned
            ("cust_C", str(today - timedelta(days=90))),   # boundary — churned
        ]
        schema = ["customer_id", "last_order_date"]
        df = spark.createDataFrame(data, schema)

        result = (
            df
            .withColumn("days_since_last_order",
                F.datediff(F.current_date(), F.to_date("last_order_date")))
            .withColumn("is_churned", F.col("days_since_last_order") > 90)
        )

        rows = {r["customer_id"]: r["is_churned"] for r in result.collect()}
        assert rows["cust_A"] == False
        assert rows["cust_B"] == True
        assert rows["cust_C"] == False  # exactly 90 days, not > 90
