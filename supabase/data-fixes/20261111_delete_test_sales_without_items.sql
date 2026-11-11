-- One-off data fix applied manually on 2026-11-11 (not a migration), confirmed by the owner.
-- Four test sales had no venta_detalle rows (left behind by the old non-atomic sale flow).
-- They were deleted and the expected cash of closed sessions recomputed.
-- Session 2bf8df41 (2026-04-21) was also a test: its declared cash was set to 1000.00
-- so it matches the only remaining sale and shows no difference in reports.
delete from public.ventas v
where v.id in (
  '06700044-ad6a-4108-9742-b957f82dc8ff', -- 2026-01-24 13000.00 Tarjeta
  'df9b0e0f-af21-440d-9392-f1754ecc2915', -- 2026-04-21 15000.00 Efectivo
  '35d94b0e-3863-4d60-971b-142b464cb474', -- 2026-04-21 15000.00 Tarjeta
  '43682327-343f-40de-a689-0da6cd0a27b3'  -- 2026-04-21  1000.00 Efectivo
)
and not exists (select 1 from public.venta_detalle d where d.venta_id = v.id);

update public.sesiones_caja s
set monto_esperado_efectivo = (public.resumen_caja(s.id) ->> 'esperado_efectivo')::numeric,
    monto_real_efectivo = case when s.id = '2bf8df41-2949-4ed7-991e-8137887714ef' then 1000 else s.monto_real_efectivo end
where s.estado = 'cerrada';
