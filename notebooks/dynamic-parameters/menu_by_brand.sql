-- 🍔 what's on the menu?
SELECT i.name AS item, i.price, b.cuisine_type
FROM caspers_kitchen.simulator.items i
JOIN caspers_kitchen.simulator.brands b ON i.brand_id = b.brand_id
WHERE b.name = :brand
ORDER BY i.price DESC
