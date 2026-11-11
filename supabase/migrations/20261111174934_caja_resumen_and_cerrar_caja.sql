-- Custom SQLSTATE codes raised by money functions (mapped by the backend):
--   MU001 no open cash session | MU002 insufficient stock | MU003 invalid input
--   MU004 record not found     | MU005 cash session is not open

create or replace function public.resumen_caja(p_sesion_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  select jsonb_build_object(
    'sesion_id', s.id,
    'estado', s.estado,
    'fecha_apertura', s.fecha_apertura,
    'monto_apertura', s.monto_apertura,
    'ventas_efectivo', coalesce(v.efectivo, 0),
    'ventas_tarjeta', coalesce(v.tarjeta, 0),
    'ventas_qr', coalesce(v.qr, 0),
    'cantidad_ventas', coalesce(v.cantidad, 0),
    'ingresos', coalesce(m.ingresos, 0),
    'egresos', coalesce(m.egresos, 0),
    'esperado_efectivo', s.monto_apertura + coalesce(v.efectivo, 0) + coalesce(m.ingresos, 0) - coalesce(m.egresos, 0)
  )
  from sesiones_caja s
  left join lateral (
    select
      sum(total) filter (where metodo_pago = 'Efectivo') as efectivo,
      sum(total) filter (where metodo_pago = 'Tarjeta') as tarjeta,
      sum(total) filter (where metodo_pago = 'QR') as qr,
      count(*) as cantidad
    from ventas where sesion_caja = s.id
  ) v on true
  left join lateral (
    select
      sum(monto) filter (where tipo = 'ingreso') as ingresos,
      sum(monto) filter (where tipo = 'egreso') as egresos
    from movimientos_caja where sesion_id = s.id
  ) m on true
  where s.id = p_sesion_id;
$$;

create or replace function public.cerrar_caja(p_sesion_id uuid, p_monto_real_efectivo numeric, p_observaciones text)
returns public.sesiones_caja
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_sesion sesiones_caja;
  v_esperado numeric;
begin
  if p_monto_real_efectivo is null or p_monto_real_efectivo < 0 then
    raise exception 'El monto real en efectivo debe ser mayor o igual a 0' using errcode = 'MU003';
  end if;

  select * into v_sesion from sesiones_caja where id = p_sesion_id for update;
  if not found then
    raise exception 'Sesión de caja no encontrada' using errcode = 'MU004';
  end if;
  if v_sesion.estado <> 'abierta' then
    raise exception 'La sesión de caja ya está cerrada' using errcode = 'MU005';
  end if;

  v_esperado := (public.resumen_caja(p_sesion_id) ->> 'esperado_efectivo')::numeric;

  update sesiones_caja
  set monto_esperado_efectivo = v_esperado,
      monto_real_efectivo = round(p_monto_real_efectivo, 2),
      fecha_cierre = now(),
      estado = 'cerrada',
      observaciones = p_observaciones
  where id = p_sesion_id
  returning * into v_sesion;

  return v_sesion;
end;
$$;

revoke execute on function public.resumen_caja(uuid) from public, anon, authenticated;
revoke execute on function public.cerrar_caja(uuid, numeric, text) from public, anon, authenticated;
grant execute on function public.resumen_caja(uuid) to service_role;
grant execute on function public.cerrar_caja(uuid, numeric, text) to service_role;
