-- Report aggregations in SQL, bucketed by Argentina local date.
-- Date params are inclusive local dates; null means unbounded.

create or replace function public.reporte_ventas(p_desde date default null, p_hasta date default null)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  with v as (
    select total, (created_at at time zone 'America/Argentina/Buenos_Aires')::date as dia
    from ventas
    where (p_desde is null or created_at >= (p_desde::timestamp at time zone 'America/Argentina/Buenos_Aires'))
      and (p_hasta is null or created_at < ((p_hasta + 1)::timestamp at time zone 'America/Argentina/Buenos_Aires'))
  ),
  d as (
    select dia, sum(total) as total, count(*) as cantidad_ventas from v group by dia
  )
  select jsonb_build_object(
    'total_ingresos', coalesce((select sum(total) from v), 0),
    'cantidad_operaciones', (select count(*) from v),
    'ventas_por_dia', coalesce((
      select jsonb_agg(jsonb_build_object('fecha', dia, 'total', total, 'cantidad_ventas', cantidad_ventas) order by dia)
      from d
    ), '[]'::jsonb)
  );
$$;

create or replace function public.reporte_productos_top(p_desde date default null, p_hasta date default null, p_limite int default 50)
returns table (
  variante_id text,
  nombre_producto text,
  talle text,
  color text,
  cantidad_vendida bigint,
  ingresos_generados numeric
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    pv.id::text,
    coalesce(p.nombre, 'Desconocido'),
    pv.talle,
    pv.color,
    sum(d.cantidad)::bigint,
    sum(d.cantidad * d.precio_unitario)
  from venta_detalle d
  join ventas v on v.id = d.venta_id
  join producto_variantes pv on pv.id = d.variante_id
  left join productos p on p.id = pv.producto_id
  where (p_desde is null or v.created_at >= (p_desde::timestamp at time zone 'America/Argentina/Buenos_Aires'))
    and (p_hasta is null or v.created_at < ((p_hasta + 1)::timestamp at time zone 'America/Argentina/Buenos_Aires'))
  group by pv.id, p.nombre, pv.talle, pv.color
  order by sum(d.cantidad * d.precio_unitario) desc
  limit greatest(coalesce(p_limite, 50), 1);
$$;

create or replace function public.reporte_cajas(p_desde date default null, p_hasta date default null)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  with s as (
    select
      ses.id,
      ses.estado,
      (ses.fecha_apertura at time zone 'America/Argentina/Buenos_Aires')::date as dia,
      ses.monto_apertura,
      ses.monto_real_efectivo,
      r.resumen
    from sesiones_caja ses
    cross join lateral (select public.resumen_caja(ses.id) as resumen) r
    where (p_desde is null or ses.fecha_apertura >= (p_desde::timestamp at time zone 'America/Argentina/Buenos_Aires'))
      and (p_hasta is null or ses.fecha_apertura < ((p_hasta + 1)::timestamp at time zone 'America/Argentina/Buenos_Aires'))
  ),
  d as (
    select
      dia,
      count(*) as sesiones,
      sum(monto_apertura) as monto_inicial_total,
      sum((resumen ->> 'ventas_efectivo')::numeric) as ventas_efectivo,
      sum((resumen ->> 'ingresos')::numeric) as ingresos,
      sum((resumen ->> 'egresos')::numeric) as egresos,
      sum(coalesce(monto_real_efectivo, 0)) filter (where estado = 'cerrada') as monto_real_efectivo_total,
      coalesce(sum(monto_real_efectivo - (resumen ->> 'esperado_efectivo')::numeric) filter (where estado = 'cerrada'), 0) as diferencia
    from s
    group by dia
  )
  select jsonb_build_object(
    'resumen_diario', coalesce((
      select jsonb_agg(jsonb_build_object(
        'fecha', dia,
        'sesiones_abiertas', sesiones,
        'monto_inicial_total', monto_inicial_total,
        'ventas_efectivo', ventas_efectivo,
        'ingresos', ingresos,
        'egresos', egresos,
        'monto_real_efectivo_total', coalesce(monto_real_efectivo_total, 0),
        'diferencia_esperado_vs_real', diferencia
      ) order by dia)
      from d
    ), '[]'::jsonb),
    'diferencia_total_periodo', coalesce((select sum(diferencia) from d), 0)
  );
$$;

revoke execute on function public.reporte_ventas(date, date) from public, anon, authenticated;
revoke execute on function public.reporte_productos_top(date, date, int) from public, anon, authenticated;
revoke execute on function public.reporte_cajas(date, date) from public, anon, authenticated;
grant execute on function public.reporte_ventas(date, date) to service_role;
grant execute on function public.reporte_productos_top(date, date, int) to service_role;
grant execute on function public.reporte_cajas(date, date) to service_role;
