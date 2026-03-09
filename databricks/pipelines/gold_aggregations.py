# databricks/pipelines/gold_aggregations.py
"""
Gold Zone Aggregation Pipeline — Business-level KPIs and curated datasets.
Reads from Silver tables and produces star-schema models for BI consumption.
"""

import dlt
from pyspark.sql import functions as F


# ─── GOLD: DAILY REVENUE SUMMARY ───────────────────────────────────────────
@dlt.table(
    name="gold_daily_revenue",
    comment="Daily revenue KPIs — primary BI dashboard source",
    table_properties={
        "quality": "gold",
        "delta.autoOptimize.optimizeWrite": "true",
        "delta.autoOptimize.autoCompact": "true",
    },
    partition_cols=["order_date"],
)
def gold_daily_revenue():
    orders = dlt.read("silver_orders").filter("__END_AT IS NULL")  # current records only

    return (
        orders
        .withColumn("order_date", F.to_date("created_at"))
        .withColumn("revenue", F.col("quantity") * F.col("unit_price").cast("double"))
        .groupBy("order_date")
        .agg(
            F.sum("revenue").alias("total_revenue"),
            F.count("order_id").alias("total_orders"),
            F.countDistinct("customer_id").alias("unique_customers"),
            F.avg("revenue").alias("avg_order_value"),
            F.sum(F.when(F.col("status") == "completed", F.col("revenue"))).alias("completed_revenue"),
            F.sum(F.when(F.col("status") == "refunded", F.col("revenue"))).alias("refunded_revenue"),
            F.count(F.when(F.col("status") == "refunded", 1)).alias("refund_count"),
        )
        .withColumn("refund_rate", F.col("refund_count") / F.col("total_orders"))
        .withColumn("updated_at", F.current_timestamp())
    )


# ─── GOLD: CUSTOMER 360 ─────────────────────────────────────────────────────
@dlt.table(
    name="gold_customer_360",
    comment="Full customer profile combining CRM data with behavioral signals",
    table_properties={
        "quality": "gold",
        "delta.autoOptimize.optimizeWrite": "true",
    },
)
def gold_customer_360():
    customers = dlt.read("silver_customers")
    orders = dlt.read("silver_orders").filter("__END_AT IS NULL")
    events = dlt.read("silver_events")

    # Order-level aggregations per customer
    customer_orders = (
        orders
        .withColumn("revenue", F.col("quantity") * F.col("unit_price").cast("double"))
        .groupBy("customer_id")
        .agg(
            F.count("order_id").alias("total_orders"),
            F.sum("revenue").alias("total_revenue"),
            F.avg("revenue").alias("avg_order_value"),
            F.max("created_at").alias("last_order_date"),
            F.min("created_at").alias("first_order_date"),
            F.count(F.when(F.col("status") == "completed", 1)).alias("completed_orders"),
        )
    )

    # Behavioral signals per customer
    customer_events = (
        events
        .groupBy("customer_id")
        .agg(
            F.count("event_id").alias("total_events"),
            F.countDistinct("session_id").alias("total_sessions"),
            F.sum(F.when(F.col("event_type") == "purchase", 1)).alias("purchase_events"),
            F.max("event_timestamp").alias("last_active_date"),
        )
    )

    return (
        customers
        .join(customer_orders, on="customer_id", how="left")
        .join(customer_events, on="customer_id", how="left")
        .withColumn("customer_segment",
            F.when(F.col("total_revenue") >= 10000, "VIP")
            .when(F.col("total_revenue") >= 1000, "High Value")
            .when(F.col("total_revenue") >= 100, "Regular")
            .otherwise("Occasional")
        )
        .withColumn("days_since_last_order",
            F.datediff(F.current_date(), F.to_date("last_order_date"))
        )
        .withColumn("is_churned",
            F.col("days_since_last_order") > 90
        )
        .withColumn("updated_at", F.current_timestamp())
    )


# ─── GOLD: PRODUCT PERFORMANCE ─────────────────────────────────────────────
@dlt.table(
    name="gold_product_performance",
    comment="Product-level sales performance and inventory metrics",
    table_properties={
        "quality": "gold",
        "delta.autoOptimize.optimizeWrite": "true",
    },
    partition_cols=["analysis_month"],
)
def gold_product_performance():
    orders = dlt.read("silver_orders").filter("__END_AT IS NULL")

    return (
        orders
        .withColumn("order_month", F.date_format("created_at", "yyyy-MM"))
        .withColumn("analysis_month", F.to_date(F.concat_ws("-", "order_month", F.lit("01"))))
        .withColumn("revenue", F.col("quantity") * F.col("unit_price").cast("double"))
        .groupBy("product_id", "analysis_month")
        .agg(
            F.sum("quantity").alias("units_sold"),
            F.sum("revenue").alias("total_revenue"),
            F.count("order_id").alias("order_count"),
            F.countDistinct("customer_id").alias("unique_buyers"),
            F.avg("unit_price").cast("double").alias("avg_selling_price"),
        )
        .withColumn("revenue_rank",
            F.rank().over(
                F.Window.partitionBy("analysis_month").orderBy(F.desc("total_revenue"))
            )
        )
        .withColumn("updated_at", F.current_timestamp())
    )


# ─── GOLD: ML FEATURES TABLE ────────────────────────────────────────────────
@dlt.table(
    name="gold_ml_customer_features",
    comment="Pre-computed ML features for customer churn and LTV models",
    table_properties={
        "quality": "gold",
        "delta.autoOptimize.optimizeWrite": "true",
    },
)
def gold_ml_customer_features():
    c360 = dlt.read("gold_customer_360")

    return (
        c360.select(
            "customer_id",
            "total_orders",
            "total_revenue",
            "avg_order_value",
            "completed_orders",
            "total_events",
            "total_sessions",
            "purchase_events",
            "days_since_last_order",
            "is_churned",
            F.col("age").alias("customer_age"),
            F.col("country").alias("customer_country"),
            F.col("customer_segment"),
            F.datediff(F.current_date(), F.to_date("signup_date")).alias("account_age_days"),
            F.when(F.col("total_sessions") > 0,
                F.col("purchase_events") / F.col("total_sessions")
            ).otherwise(0.0).alias("purchase_conversion_rate"),
        )
        .withColumn("feature_timestamp", F.current_timestamp())
    )
