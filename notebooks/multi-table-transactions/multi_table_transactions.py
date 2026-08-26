# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Table Transactions
# MAGIC `BEGIN ATOMIC ... END` wraps multiple table writes into one statement. Everything commits or everything rolls back.
# MAGIC
# MAGIC Requires **Runtime 18.0+** and Unity Catalog **managed tables**.
# MAGIC
# MAGIC [Docs](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-txn-begin-atomic) [Data Generator 👻](https://github.com/databricks-solutions/caspers-kitchens)

# COMMAND ----------

# MAGIC %sql
# MAGIC -- 🎛️ Casper's ghost kitchen brands and their menus: two tables that need to stay in sync
# MAGIC SELECT * FROM caspers_kitchen.simulator.brands LIMIT 5;

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM caspers_kitchen.simulator.menus LIMIT 5;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- ✅ onboard a new brand: the brand AND its menu land together or not at all
# MAGIC BEGIN ATOMIC
# MAGIC   INSERT INTO caspers_kitchen.simulator.brands VALUES (999, 'The Golden Falafel', 'Mediterranean', 11);
# MAGIC   INSERT INTO caspers_kitchen.simulator.menus VALUES (999, 999, 'The Golden Falafel Menu');
# MAGIC END;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- both landed 👇
# MAGIC SELECT 'brands' AS tbl, name FROM caspers_kitchen.simulator.brands WHERE brand_id = 999
# MAGIC UNION ALL
# MAGIC SELECT 'menus', name FROM caspers_kitchen.simulator.menus WHERE id = 999;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- 🫠 now break the second insert: fake_column doesn't exist
# MAGIC -- first insert is valid but the whole block rolls back
# MAGIC BEGIN ATOMIC
# MAGIC   INSERT INTO caspers_kitchen.simulator.brands VALUES (998, 'Main Character Meals 💅', '✨ Influencer ✨', 5);
# MAGIC   INSERT INTO caspers_kitchen.simulator.menus SELECT fake_column FROM caspers_kitchen.simulator.menus;
# MAGIC END;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- no Main Character Meals 💅. the whole block rolled back. 🧹
# MAGIC SELECT * FROM caspers_kitchen.simulator.brands WHERE brand_id = 998;