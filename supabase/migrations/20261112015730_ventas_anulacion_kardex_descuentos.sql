-- Phase 5 batch 1: sale cancellation, stock ledger (kardex) and whole-sale discount/surcharge.
-- New SQLSTATE codes: MU006 sale already cancelled | MU007 discount above the allowed limit.
-- New function names (registrar_venta, registrar_ajuste_stock) replace crear_venta / ajustar_stock,
-- which stay in place until they can be dropped. Existing rows get subtotal via a separate data fix.

-- 1. Sale status and amounts --------------------------------------------------
alter table public.ventas
  add column estado text not null default 'completada',
  add column subtotal numeric not null default 0,
  add column anulada_at timestamptz,
  add column anulada_por uuid references public.perfiles (id),
  add column motivo_anulacion text,
  add constraint ventas_estado_valido check (estado in ('completada', 'anulada')),
  add constraint ventas_descuento_no_negativo check (descuento_aplicado >= 0),
  add constraint ventas_recargo_no_negativo check (recargo_aplicado >= 0);

create index ventas_estado_idx on public.ventas (estado);
create index ventas_anulada_por_idx on public.ventas (anulada_por);

-- 2. Stock ledger ---------------------------------------------------------------
create table public.movimientos_stock (
  id bigint generated always as identity primary key,
  variante_id uuid not null references public.producto_variantes (id),
  tipo text not null check (tipo in ('venta', 'anulacion', 'ajuste')),
  cantidad int not null check (cantidad <> 0),
  stock_resultante int not null check (stock_resultante >= 0),
  venta_id uuid references public.ventas (id),
  usuario_id uuid references public.perfiles (id),
  motivo text,
  created_at timestamptz not null default now()
);
alter table public.movimientos_stock enable row level security;
create index movimientos_stock_variante_created_idx on public.movimientos_stock (variante_id, created_at desc);
create index movimientos_stock_venta_id_idx on public.movimientos_stock (venta_id);
create index movimientos_stock_usuario_id_idx on public.movimientos_stock (usuario_id);
revoke all on public.movimientos_stock from anon, authenticated;
grant all on public.movimientos_stock to service_role;

-- 3. Sale creation with discount/surcharge and kardex ----------------------------
-- p_descuento_tipo / p_recargo_tipo: null | 'porcentaje' | 'monto'. Employees (p_es_admin = false)
-- can discount at most 10% of the subtotal. Prices always come from the database.
create or replace function public.registrar_venta(
  p_usuario_id uuid,
  p_metodo_pago text,
  p_items jsonb,
  p_cliente_id uuid default null,
  p_idempotency_key text default null,
  p_descuento_tipo text default null,
  p_descuento_valor numeric default 0,
  p_recargo_tipo text default null,
  p_recargo_valor numeric default 0,
  p_es_admin boolean default false
)
returns public.ventas
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_venta ventas;
  v_sesion_id uuid;
  v_item record;
  v_variante record;
  v_subtotal numeric := 0;
  v_total_costo numeric := 0;
  v_descuento numeric := 0;
  v_recargo numeric := 0;
  v_stock int;
begin
  if p_idempotency_key is not null then
    select * into v_venta from ventas where idempotency_key = p_idempotency_key;
    if found then
      return v_venta;
    end if;
  end if;

  if p_metodo_pago is null or p_metodo_pago not in ('Efectivo', 'Tarjeta', 'QR') then
    raise exception 'Método de pago inválido' using errcode = 'MU003';
  end if;
  if p_items is null or jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) = 0 then
    raise exception 'La venta debe tener al menos un item' using errcode = 'MU003';
  end if;
  if exists (
    select 1 from jsonb_array_elements(p_items) e
    where (e ->> 'variante_id') is null or (e ->> 'cantidad') is null or (e ->> 'cantidad')::int <= 0
  ) then
    raise exception 'Cada item debe tener variante y cantidad mayor a 0' using errcode = 'MU003';
  end if;
  if coalesce(p_descuento_tipo, 'porcentaje') not in ('porcentaje', 'monto')
     or coalesce(p_recargo_tipo, 'porcentaje') not in ('porcentaje', 'monto')
     or coalesce(p_descuento_valor, 0) < 0 or coalesce(p_recargo_valor, 0) < 0
     or (p_descuento_tipo = 'porcentaje' and p_descuento_valor > 100) then
    raise exception 'Descuento o recargo inválido' using errcode = 'MU003';
  end if;

  select id into v_sesion_id from sesiones_caja where estado = 'abierta' for share;
  if v_sesion_id is null then
    raise exception 'No hay sesión de caja abierta.' using errcode = 'MU001';
  end if;

  begin
    insert into ventas (cliente_id, usuario_id, sesion_caja, total, total_costo, metodo_pago, idempotency_key)
    values (p_cliente_id, p_usuario_id, v_sesion_id, 0, 0, p_metodo_pago, p_idempotency_key)
    returning * into v_venta;
  exception when unique_violation then
    select * into v_venta from ventas where idempotency_key = p_idempotency_key;
    return v_venta;
  end;

  for v_item in
    select (e ->> 'variante_id')::uuid as variante_id, sum((e ->> 'cantidad')::int) as cantidad
    from jsonb_array_elements(p_items) e
    group by 1
    order by 1
  loop
    select id, precio_venta, coalesce(precio_costo, 0) as precio_costo, stock_actual
      into v_variante
      from producto_variantes
     where id = v_item.variante_id
       for update;
    if not found then
      raise exception 'Variante % no encontrada', v_item.variante_id using errcode = 'MU004';
    end if;
    if v_variante.stock_actual < v_item.cantidad then
      raise exception 'Stock insuficiente para la variante %', v_item.variante_id using errcode = 'MU002';
    end if;

    update producto_variantes
       set stock_actual = stock_actual - v_item.cantidad,
           updated_at = now()
     where id = v_item.variante_id
    returning stock_actual into v_stock;

    insert into venta_detalle (venta_id, variante_id, cantidad, precio_unitario, costo_unitario)
    values (v_venta.id, v_item.variante_id, v_item.cantidad, v_variante.precio_venta, v_variante.precio_costo);

    insert into movimientos_stock (variante_id, tipo, cantidad, stock_resultante, venta_id, usuario_id)
    values (v_item.variante_id, 'venta', -v_item.cantidad, v_stock, v_venta.id, p_usuario_id);

    v_subtotal := v_subtotal + v_item.cantidad * v_variante.precio_venta;
    v_total_costo := v_total_costo + v_item.cantidad * v_variante.precio_costo;
  end loop;

  v_subtotal := round(v_subtotal, 2);
  v_descuento := round(case p_descuento_tipo
    when 'porcentaje' then v_subtotal * coalesce(p_descuento_valor, 0) / 100
    when 'monto' then coalesce(p_descuento_valor, 0)
    else 0 end, 2);
  if v_descuento > v_subtotal then
    raise exception 'El descuento no puede superar el subtotal' using errcode = 'MU003';
  end if;
  if not coalesce(p_es_admin, false) and v_descuento > round(v_subtotal * 0.10, 2) then
    raise exception 'El descuento máximo permitido para empleados es 10%%' using errcode = 'MU007';
  end if;
  v_recargo := round(case p_recargo_tipo
    when 'porcentaje' then (v_subtotal - v_descuento) * coalesce(p_recargo_valor, 0) / 100
    when 'monto' then coalesce(p_recargo_valor, 0)
    else 0 end, 2);

  update ventas
     set subtotal = v_subtotal,
         descuento_aplicado = v_descuento,
         recargo_aplicado = v_recargo,
         total = v_subtotal - v_descuento + v_recargo,
         total_costo = round(v_total_costo, 2)
   where id = v_venta.id
  returning * into v_venta;

  return v_venta;
end;
$$;

-- 4. Sale cancellation -------------------------------------------------------------
create or replace function public.anular_venta(p_venta_id uuid, p_usuario_id uuid, p_motivo text)
returns public.ventas
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_venta ventas;
  v_item record;
  v_stock int;
  v_sesion_abierta uuid;
begin
  if p_motivo is null or length(trim(p_motivo)) = 0 then
    raise exception 'El motivo de anulación es obligatorio' using errcode = 'MU003';
  end if;

  select * into v_venta from ventas where id = p_venta_id for update;
  if not found then
    raise exception 'Venta no encontrada' using errcode = 'MU004';
  end if;
  if v_venta.estado = 'anulada' then
    raise exception 'La venta ya está anulada' using errcode = 'MU006';
  end if;

  select id into v_sesion_abierta from sesiones_caja where estado = 'abierta' for share;

  -- A cash sale from a closed session is refunded from the currently open register.
  if v_venta.metodo_pago = 'Efectivo' and v_venta.total > 0
     and v_venta.sesion_caja is distinct from v_sesion_abierta then
    if v_sesion_abierta is null then
      raise exception 'Abrí la caja para registrar la devolución en efectivo' using errcode = 'MU001';
    end if;
    insert into movimientos_caja (sesion_id, tipo, monto, motivo)
    values (v_sesion_abierta, 'egreso', v_venta.total,
            left('Anulación venta ' || left(v_venta.id::text, 8) || ': ' || trim(p_motivo), 200));
  end if;

  for v_item in
    select variante_id, sum(cantidad)::int as cantidad
    from venta_detalle where venta_id = p_venta_id
    group by variante_id
    order by variante_id
  loop
    update producto_variantes
       set stock_actual = stock_actual + v_item.cantidad,
           updated_at = now()
     where id = v_item.variante_id
    returning stock_actual into v_stock;

    insert into movimientos_stock (variante_id, tipo, cantidad, stock_resultante, venta_id, usuario_id, motivo)
    values (v_item.variante_id, 'anulacion', v_item.cantidad, v_stock, p_venta_id, p_usuario_id, trim(p_motivo));
  end loop;

  update ventas
     set estado = 'anulada',
         anulada_at = now(),
         anulada_por = p_usuario_id,
         motivo_anulacion = trim(p_motivo)
   where id = p_venta_id
  returning * into v_venta;

  return v_venta;
end;
$$;

-- 5. Stock adjustment with kardex --------------------------------------------------
create or replace function public.registrar_ajuste_stock(
  p_variante_id uuid, p_cantidad int, p_usuario_id uuid, p_motivo text
)
returns public.producto_variantes
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_variante producto_variantes;
begin
  if p_cantidad is null or p_cantidad = 0 then
    raise exception 'La cantidad a ajustar no puede ser 0' using errcode = 'MU003';
  end if;

  select * into v_variante from producto_variantes where id = p_variante_id for update;
  if not found then
    raise exception 'Variante no encontrada' using errcode = 'MU004';
  end if;
  if v_variante.stock_actual + p_cantidad < 0 then
    raise exception 'El ajuste dejaría el stock en negativo' using errcode = 'MU002';
  end if;

  update producto_variantes
     set stock_actual = stock_actual + p_cantidad,
         updated_at = now()
   where id = p_variante_id
  returning * into v_variante;

  insert into movimientos_stock (variante_id, tipo, cantidad, stock_resultante, usuario_id, motivo)
  values (p_variante_id, 'ajuste', p_cantidad, v_variante.stock_actual, p_usuario_id, nullif(trim(p_motivo), ''));

  return v_variante;
end;
$$;

-- 6. Cancelled sales no longer count in cash summary and reports -------------------
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
    from ventas where sesion_caja = s.id and estado = 'completada'
  ) v on true
  left join lateral (
    select
      sum(monto) filter (where tipo = 'ingreso') as ingresos,
      sum(monto) filter (where tipo = 'egreso') as egresos
    from movimientos_caja where sesion_id = s.id
  ) m on true
  where s.id = p_sesion_id;
$$;

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
    where estado = 'completada'
      and (p_desde is null or created_at >= (p_desde::timestamp at time zone 'America/Argentina/Buenos_Aires'))
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
  where v.estado = 'completada'
    and (p_desde is null or v.created_at >= (p_desde::timestamp at time zone 'America/Argentina/Buenos_Aires'))
    and (p_hasta is null or v.created_at < ((p_hasta + 1)::timestamp at time zone 'America/Argentina/Buenos_Aires'))
  group by pv.id, p.nombre, pv.talle, pv.color
  order by sum(d.cantidad * d.precio_unitario) desc
  limit greatest(coalesce(p_limite, 50), 1);
$$;

revoke execute on function public.registrar_venta(uuid, text, jsonb, uuid, text, text, numeric, text, numeric, boolean) from public, anon, authenticated;
revoke execute on function public.anular_venta(uuid, uuid, text) from public, anon, authenticated;
revoke execute on function public.registrar_ajuste_stock(uuid, int, uuid, text) from public, anon, authenticated;
grant execute on function public.registrar_venta(uuid, text, jsonb, uuid, text, text, numeric, text, numeric, boolean) to service_role;
grant execute on function public.anular_venta(uuid, uuid, text) to service_role;
grant execute on function public.registrar_ajuste_stock(uuid, int, uuid, text) to service_role;
