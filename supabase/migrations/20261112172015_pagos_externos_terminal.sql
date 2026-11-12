-- Stage B: payment terminal core (provider-agnostic; Clover plugs in later).
-- New SQLSTATE code: MU011 total changed since the charge started.

-- 1. One row per charge attempt on a payment terminal ----------------------------
create table public.pagos_externos (
  id uuid primary key default gen_random_uuid(),
  proveedor text not null default 'fake',
  external_payment_id text not null unique check (length(external_payment_id) <= 32),
  estado text not null check (estado in (
    'pendiente', 'enviado', 'aprobado', 'rechazado', 'cancelado',
    'indeterminado', 'venta_registrada', 'error_registro', 'reembolsado')),
  metodo_pago text not null check (metodo_pago in ('Tarjeta', 'QR')),
  monto numeric not null check (monto > 0),
  carrito jsonb not null,
  venta_id uuid references public.ventas (id),
  sesion_caja uuid references public.sesiones_caja (id),
  usuario_id uuid references public.perfiles (id),
  proveedor_payment_id text,
  tarjeta_marca text,
  tarjeta_ultimos4 text check (tarjeta_ultimos4 is null or tarjeta_ultimos4 ~ '^[0-9]{4}$'),
  codigo_autorizacion text,
  cuotas int check (cuotas is null or cuotas between 1 and 99),
  tipo_ingreso text,
  respuesta jsonb,
  error text,
  intentos_conciliacion int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Only one charge in flight at a time (single terminal, single global register).
create unique index pagos_externos_un_cobro_activo on public.pagos_externos ((true))
  where estado in ('pendiente', 'enviado', 'indeterminado');
create index pagos_externos_estado_idx on public.pagos_externos (estado, updated_at);
create index pagos_externos_venta_id_idx on public.pagos_externos (venta_id);
create index pagos_externos_sesion_caja_idx on public.pagos_externos (sesion_caja);
create index pagos_externos_usuario_id_idx on public.pagos_externos (usuario_id);

alter table public.pagos_externos enable row level security;
revoke all on public.pagos_externos from anon, authenticated;
grant all on public.pagos_externos to service_role;

-- 2. Terminal integration settings (single row; OAuth tokens used in stage C) ----
create table public.integracion_terminal (
  id int primary key default 1 check (id = 1),
  proveedor text not null default 'fake' check (proveedor in ('fake', 'clover')),
  habilitado boolean not null default false,
  merchant_id text,
  device_id text,
  pos_id text,
  access_token_cifrado text,
  refresh_token_cifrado text,
  access_expira_at timestamptz,
  updated_at timestamptz not null default now(),
  updated_by uuid references public.perfiles (id)
);
create index integracion_terminal_updated_by_idx on public.integracion_terminal (updated_by);
alter table public.integracion_terminal enable row level security;
revoke all on public.integracion_terminal from anon, authenticated;
grant all on public.integracion_terminal to service_role;

-- 3. Link sales to the charge that paid them ----------------------------------------
alter table public.ventas add column pago_externo_id uuid references public.pagos_externos (id);
create unique index ventas_pago_externo_id_key on public.ventas (pago_externo_id) where pago_externo_id is not null;

-- 4. Quote a sale without writing anything (same rules as registrar_venta) --------
create or replace function public.cotizar_venta(
  p_items jsonb,
  p_descuento_tipo text default null,
  p_descuento_valor numeric default 0,
  p_recargo_tipo text default null,
  p_recargo_valor numeric default 0,
  p_es_admin boolean default false
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = public
as $$
declare
  v_item record;
  v_variante record;
  v_subtotal numeric := 0;
  v_descuento numeric := 0;
  v_recargo numeric := 0;
  v_limite numeric;
begin
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
  if not exists (select 1 from sesiones_caja where estado = 'abierta') then
    raise exception 'No hay sesión de caja abierta.' using errcode = 'MU001';
  end if;

  for v_item in
    select (e ->> 'variante_id')::uuid as variante_id, sum((e ->> 'cantidad')::int) as cantidad
    from jsonb_array_elements(p_items) e
    group by 1
  loop
    select precio_venta, stock_actual into v_variante from producto_variantes where id = v_item.variante_id;
    if not found then
      raise exception 'Variante % no encontrada', v_item.variante_id using errcode = 'MU004';
    end if;
    if v_variante.stock_actual < v_item.cantidad then
      raise exception 'Stock insuficiente para la variante %', v_item.variante_id using errcode = 'MU002';
    end if;
    v_subtotal := v_subtotal + v_item.cantidad * v_variante.precio_venta;
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
    raise exception using errcode = 'MU007',
      message = 'El descuento máximo permitido para empleados es ' || trim_scale(v_limite)::text || '%';
  end if;
  v_recargo := round(case p_recargo_tipo
    when 'porcentaje' then (v_subtotal - v_descuento) * coalesce(p_recargo_valor, 0) / 100
    when 'monto' then coalesce(p_recargo_valor, 0)
    else 0 end, 2);

  return jsonb_build_object(
    'subtotal', v_subtotal,
    'descuento', v_descuento,
    'recargo', v_recargo,
    'total', v_subtotal - v_descuento + v_recargo
  );
end;
$$;

-- 5. Register the sale of an approved charge ------------------------------------------
-- Same as registrar_venta (idempotency key = charge id) but fails with MU011 if the
-- total differs from what was charged; the raise rolls back the whole sale.
create or replace function public.registrar_venta_con_pago(
  p_pago_externo_id uuid,
  p_usuario_id uuid,
  p_metodo_pago text,
  p_items jsonb,
  p_total_esperado numeric,
  p_cliente_id uuid default null,
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
begin
  v_venta := public.registrar_venta(
    p_usuario_id, p_metodo_pago, p_items, p_cliente_id, 'pago:' || p_pago_externo_id::text,
    p_descuento_tipo, p_descuento_valor, p_recargo_tipo, p_recargo_valor, p_es_admin
  );
  if v_venta.total <> round(p_total_esperado, 2) then
    raise exception using errcode = 'MU011',
      message = 'El total cambió desde que se inició el cobro (' || v_venta.total::text
                || ' vs ' || round(p_total_esperado, 2)::text || ')';
  end if;
  update ventas set pago_externo_id = p_pago_externo_id where id = v_venta.id and pago_externo_id is null
  returning * into v_venta;
  if v_venta.id is null then
    select * into v_venta from ventas where pago_externo_id = p_pago_externo_id;
  end if;
  return v_venta;
end;
$$;

revoke execute on function public.cotizar_venta(jsonb, text, numeric, text, numeric, boolean) from public, anon, authenticated;
revoke execute on function public.registrar_venta_con_pago(uuid, uuid, text, jsonb, numeric, uuid, text, numeric, text, numeric, boolean) from public, anon, authenticated;
grant execute on function public.cotizar_venta(jsonb, text, numeric, text, numeric, boolean) to service_role;
grant execute on function public.registrar_venta_con_pago(uuid, uuid, text, jsonb, numeric, uuid, text, numeric, text, numeric, boolean) to service_role;
