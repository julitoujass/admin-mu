-- One-off data fix applied manually on 2026-11-12 (not a migration).
-- Backfilled the new ventas.subtotal column (migration 20261112015730) for rows that existed before it.
update public.ventas set subtotal = total + coalesce(descuento_aplicado, 0) - coalesce(recargo_aplicado, 0) where subtotal = 0;
