# Databricks notebook source
# MAGIC %md
# MAGIC # 🔔 SQL Alert Task for Jobs
# MAGIC
# MAGIC You can now add a SQL alert as a task in a Databricks job. The job checks the alert condition as part of your workflow, running alongside your pipeline instead of on a separate schedule.
# MAGIC
# MAGIC **Beta** - workspace admin needs to enable it at `Previews` > `Alert Job Task`. Requires a serverless or pro SQL warehouse.
# MAGIC
# MAGIC [Docs](https://docs.databricks.com/aws/en/jobs/alert) [Data Generator 👻](https://github.com/databricks-solutions/caspers-kitchens)
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC - Create a new alert: paste `🕵️ DQ check` into the alert editor. Set condition to **Rows > 0**. Save and name it.
# MAGIC - Create a new job: Jobs & Pipelines → Create → Job
# MAGIC - Click **Add another task type** → search **SQL Alert** → select it
# MAGIC - Pick the alert you just created
# MAGIC - Run the job. 
# MAGIC - The task **succeeds** either way. "Succeeded" means the alert evaluated without errors, not that the condition was OK. Check the alert status separately for TRIGGERED vs OK.

# COMMAND ----------

# DBTITLE 1,🕵️ DQ check
# MAGIC %sql
# MAGIC -- 🕵️ DQ check🕵️ data quality check: brands that got onboarded without a menu
# MAGIC SELECT b.name AS brand, b.cuisine_type,
# MAGIC  COUNT(i.id) AS item_count
# MAGIC FROM caspers_kitchen.simulator.brands b
# MAGIC LEFT JOIN caspers_kitchen.simulator.items i 
# MAGIC ON b.brand_id = i.brand_id
# MAGIC GROUP BY b.name, b.cuisine_type
# MAGIC HAVING COUNT(i.id) = 0