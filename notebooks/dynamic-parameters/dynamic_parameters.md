# 🎚️ Dynamic Parameters

The SQL editor's new Dynamic dropdown widget type populates a parameter list from a saved query instead of a static list. When the underlying data changes, the dropdown updates automatically.

Requires the **new SQL editor** (not classic). SQL warehouse only (not notebooks).

[Docs](https://docs.databricks.com/aws/en/sql/user/sql-editor/parameter-widgets#dynamic-dropdown) [Data Generator 👻](https://github.com/databricks-solutions/caspers-kitchens)

---

- Open and run `brand_list.sql`, save it (this feeds the dropdown)
- Open `menu_by_brand.sql` — a `:brand` widget appears
- Click ⚙️ on the widget → **Dynamic dropdown** → select **📝 Brand List** → pick McDoodles as the default → Apply
- Run it, swap between brands: McDoodles (15 items), NootroNourish (Nootropic Cafe, obviously), The Golden Falafel (0 items, just onboarded, no menu yet)
- New brands added to `caspers_kitchen.simulator.brands` show up in the dropdown automatically. No widget editing needed.
