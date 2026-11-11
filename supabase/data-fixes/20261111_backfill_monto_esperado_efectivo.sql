-- One-off data fix applied manually on 2026-11-11 (not a migration).
-- The old finalizar_cierre_caja compared metodo_pago with 'efectivo' while sales store 'Efectivo',
-- so expected cash ignored every cash sale. Recomputed with the corrected resumen_caja formula.
-- Result: only session 2bf8df41-2949-4ed7-991e-8137887714ef changed (0.00 -> 17000.00).
update public.sesiones_caja s
set monto_esperado_efectivo = (public.resumen_caja(s.id) ->> 'esperado_efectivo')::numeric
where s.estado = 'cerrada';
