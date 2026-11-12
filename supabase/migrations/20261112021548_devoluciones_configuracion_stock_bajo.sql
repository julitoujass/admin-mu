-- Phase 5 batch 2: partial returns, business settings and low-stock lookup.
-- New SQLSTATE codes: MU008 sale is cancelled | MU009 return quantity above what is left to return
--                     MU010 sale has returns (cannot be cancelled).

-- 1. Business settings (single row, id = 1; the row itself is inserted by a data fix) ---------
create table public.configuracion (
  id int primary key default 1 check (id = 1),
  nombre_negocio text not null default 'Mundo Uniforme',
  cuit text,
  direccion text,
  telefono text,
  email text,
  pie_ticket text,
  descuento_max_empleado numeric not null default 10 check (descuento_max_empleado between 0 and 100),
  updated_at timestamptz not null default now(),
  updated_by uuid references public.perfiles (id)
);
alter table public.configuracion enable row level security;
create index configuracion_updated_by_idx on public.configuracion (updated_by);
revoke all on public.configuracion from anon, authenticated;
grant all on public.configuracion to service_role;

-- 2. Returns ------------------------------------------------------------------------------
create table public.devoluciones (
  id uuid primary key default gen_random_uuid(),
  venta_id uuid not null references public.ventas (id),
  usuario_id uuid references public.perfiles (id),
  motivo text not null,
  metodo_pago text not null check (metodo_pago in ('Efectivo', 'Tarjeta', 'QR')),
  monto numeric not null check (monto >= 0),
  sesion_caja uuid references public.sesiones_caja (id),
  created_at timestamptz not null default now()
);
create table public.devolucion_items (
  id bigint generated always as identity primary key,
  devolucion_id uuid not null references public.devoluciones (id) on delete cascade,
  variante_id uuid not null references public.producto_variantes (id),
  cantidad int not null check (cantidad > 0),
  monto numeric not null check (monto >= 0)
);
alter table public.devoluciones enable row level security;
alter table public.devolucion_items enable row level security;
create index devoluciones_venta_id_idx on public.devoluciones (venta_id);
create index devoluciones_created_at_idx on public.devoluciones (created_at);
create index devoluciones_usuario_id_idx on public.devoluciones (usuario_id);
create index devoluciones_sesion_caja_idx on public.devoluciones (sesion_caja);
create index devolucion_items_devolucion_id_idx on public.devolucion_items (devolucion_id);
create index devolucion_items_variante_id_idx on public.devolucion_items (variante_id);
revoke all on public.devoluciones, public.devolucion_items from anon, authenticated;
grant all on public.devoluciones, public.devolucion_items to service_role;

-- p_items: [{"variante_id": uuid, "cantidad": int}]. Refund per item = precio_unitario * cantidad
-- scaled by total/subtotal, so the sale's discount and surcharge are applied proportionally.
create or replace function public.registrar_devolucion(
  p_venta_id uuid, p_usuario_id uuid, p_motivo text, p_items jsonb
)
returns public.devoluciones
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_venta ventas;
  v_dev devoluciones;
  v_item record;
  v_vendido int;
  v_devuelto int;
  v_precio numeric;
  v_factor numeric;
  v_monto_item numeric;
  v_total numeric := 0;
  v_stock int;
  v_sesion uuid;
begin
  if p_motivo is null or length(trim(p_motivo)) = 0 then
    raise exception 'El motivo de la devolución es obligatorio' using errcode = 'MU003';
  end if;
  if p_items is null or jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) = 0 then
    raise exception 'La devolución debe tener al menos un item' using errcode = 'MU003';
  end if;
  if exists (
    select 1 from jsonb_array_elements(p_items) e
    where (e ->> 'variante_id') is null or (e ->> 'cantidad') is null or (e ->> 'cantidad')::int <= 0
  ) then
    raise exception 'Cada item debe tener variante y cantidad mayor a 0' using errcode = 'MU003';
  end if;

  select * into v_venta from ventas where id = p_venta_id for update;
  if not found then
    raise exception 'Venta no encontrada' using errcode = 'MU004';
  end if;
  if v_venta.estado = 'anulada' then
    raise exception 'No se puede devolver una venta anulada' using errcode = 'MU008';
  end if;

  if v_venta.metodo_pago = 'Efectivo' then
    select id into v_sesion from sesiones_caja where estado = 'abierta' for share;
    if v_sesion is null then
      raise exception 'Abrí la caja para registrar la devolución en efectivo' using errcode = 'MU001';
    end if;
  end if;

  v_factor := case when v_venta.subtotal > 0 then v_venta.total / v_venta.subtotal else 1 end;

  insert into devoluciones (venta_id, usuario_id, motivo, metodo_pago, monto, sesion_caja)
  values (p_venta_id, p_usuario_id, trim(p_motivo), v_venta.metodo_pago, 0, v_sesion)
  returning * into v_dev;

  for v_item in
    select (e ->> 'variante_id')::uuid as variante_id, sum((e ->> 'cantidad')::int) as cantidad
    from jsonb_array_elements(p_items) e
    group by 1
    order by 1
  loop
    select coalesce(sum(cantidad), 0), max(precio_unitario) into v_vendido, v_precio
      from venta_detalle where venta_id = p_venta_id and variante_id = v_item.variante_id;
    if v_vendido = 0 then
      raise exception 'La variante % no forma parte de la venta', v_item.variante_id using errcode = 'MU003';
    end if;
    select coalesce(sum(di.cantidad), 0) into v_devuelto
      from devolucion_items di join devoluciones d on d.id = di.devolucion_id
     where d.venta_id = p_venta_id and di.variante_id = v_item.variante_id;
    if v_devuelto + v_item.cantidad > v_vendido then
      raise exception 'La cantidad a devolver supera lo pendiente de la variante %', v_item.variante_id using errcode = 'MU009';
    end if;

    v_monto_item := round(v_precio * v_item.cantidad * v_factor, 2);
    v_total := v_total + v_monto_item;

    insert into devolucion_items (devolucion_id, variante_id, cantidad, monto)
    values (v_dev.id, v_item.variante_id, v_item.cantidad, v_monto_item);

    update producto_variantes
       set stock_actual = stock_actual + v_item.cantidad,
           updated_at = now()
     where id = v_item.variante_id
    returning stock_actual into v_stock;

    insert into movimientos_stock (variante_id, tipo, cantidad, stock_resultante, venta_id, usuario_id, motivo)
    values (v_item.variante_id, 'devolucion', v_item.cantidad, v_stock, p_venta_id, p_usuario_id, trim(p_motivo));
  end loop;

  update devoluciones set monto = v_total where id = v_dev.id returning * into v_dev;

  if v_venta.metodo_pago = 'Efectivo' and v_total > 0 then
    insert into movimientos_caja (sesion_id, tipo, monto, motivo)
    values (v_sesion, 'egreso', v_total,
            left('Devolución venta ' || left(p_venta_id::text, 8) || ': ' || trim(p_motivo), 200));
  end if;

  return v_dev;
end;
$$;

-- 3. Cancellation is blocked once a sale has returns ---------------------------------------
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
  if exists (select 1 from devoluciones where venta_id = p_venta_id) then
    raise exception 'La venta tiene devoluciones; registrá una devolución por lo pendiente' using errcode = 'MU010';
  end if;

  select id into v_sesion_abierta from sesiones_caja where estado = 'abierta' for share;

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

-- 4. Sale creation reads the employee discount limit from settings -------------------------
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
  v_limite numeric;
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
  select coalesce((select descuento_max_empleado from configuracion where id = 1), 10) into v_limite;
  if not coalesce(p_es_admin, false) and v_descuento > round(v_subtotal * v_limite / 100, 2) then
    raise exception 'El descuento máximo permitido para empleados es %%%', trim(to_char(v_limite, 'FM990D##')) using errcode = 'MU007';
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

-- 5. Low stock -------------------------------------------------------------------------------
create or replace function public.variantes_stock_bajo()
returns table (
  variante_id uuid, producto_id uuid, producto_nombre text, sku text, talle text, color text,
  stock_actual int, stock_minimo int
)
language sql
stable
security invoker
set search_path = public
as $$
  select pv.id, p.id, p.nombre, pv.sku, pv.talle, pv.color, pv.stock_actual, pv.stock_minimo
  from producto_variantes pv
  join productos p on p.id = pv.producto_id
  where pv.stock_minimo is not null and pv.stock_actual <= pv.stock_minimo
  order by (pv.stock_actual - pv.stock_minimo), p.nombre, pv.talle;
$$;

-- 6. Net reports (sales minus returns, by return date) ----------------------------------------
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
  r as (
    select monto, (created_at at time zone 'America/Argentina/Buenos_Aires')::date as dia
    from devoluciones
    where (p_desde is null or created_at >= (p_desde::timestamp at time zone 'America/Argentina/Buenos_Aires'))
      and (p_hasta is null or created_at < ((p_hasta + 1)::timestamp at time zone 'America/Argentina/Buenos_Aires'))
  ),
  d as (
    select dia,
           sum(bruto) as bruto,
           sum(devuelto) as devuelto,
           sum(cantidad) as cantidad_ventas
    from (
      select dia, total as bruto, 0::numeric as devuelto, 1 as cantidad from v
      union all
      select dia, 0, monto, 0 from r
    ) x
    group by dia
  )
  select jsonb_build_object(
    'total_ingresos', coalesce((select sum(total) from v), 0) - coalesce((select sum(monto) from r), 0),
    'total_bruto', coalesce((select sum(total) from v), 0),
    'total_devoluciones', coalesce((select sum(monto) from r), 0),
    'cantidad_operaciones', (select count(*) from v),
    'ventas_por_dia', coalesce((
      select jsonb_agg(jsonb_build_object(
        'fecha', dia, 'total', bruto - devuelto, 'bruto', bruto, 'devoluciones', devuelto,
        'cantidad_ventas', cantidad_ventas) order by dia)
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
  with vendidos as (
    select d.variante_id, sum(d.cantidad) as cantidad, sum(d.cantidad * d.precio_unitario) as ingresos
    from venta_detalle d
    join ventas v on v.id = d.venta_id
    where v.estado = 'completada'
      and (p_desde is null or v.created_at >= (p_desde::timestamp at time zone 'America/Argentina/Buenos_Aires'))
      and (p_hasta is null or v.created_at < ((p_hasta + 1)::timestamp at time zone 'America/Argentina/Buenos_Aires'))
    group by d.variante_id
  ),
  devueltos as (
    select di.variante_id, sum(di.cantidad) as cantidad, sum(di.monto) as monto
    from devolucion_items di
    join devoluciones dv on dv.id = di.devolucion_id
    where (p_desde is null or dv.created_at >= (p_desde::timestamp at time zone 'America/Argentina/Buenos_Aires'))
      and (p_hasta is null or dv.created_at < ((p_hasta + 1)::timestamp at time zone 'America/Argentina/Buenos_Aires'))
    group by di.variante_id
  )
  select
    pv.id::text,
    coalesce(p.nombre, 'Desconocido'),
    pv.talle,
    pv.color,
    (vd.cantidad - coalesce(dv.cantidad, 0))::bigint,
    vd.ingresos - coalesce(dv.monto, 0)
  from vendidos vd
  join producto_variantes pv on pv.id = vd.variante_id
  left join productos p on p.id = pv.producto_id
  left join devueltos dv on dv.variante_id = vd.variante_id
  order by vd.ingresos - coalesce(dv.monto, 0) desc
  limit greatest(coalesce(p_limite, 50), 1);
$$;

revoke execute on function public.registrar_devolucion(uuid, uuid, text, jsonb) from public, anon, authenticated;
revoke execute on function public.variantes_stock_bajo() from public, anon, authenticated;
grant execute on function public.registrar_devolucion(uuid, uuid, text, jsonb) to service_role;
grant execute on function public.variantes_stock_bajo() to service_role;
