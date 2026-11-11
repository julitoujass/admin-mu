-- Atomic sale creation. Prices and costs come from the database, never from the client.
-- p_items: jsonb array of {"variante_id": uuid, "cantidad": int}; duplicate variants are merged.
-- Raises MU001 (no open session), MU002 (insufficient stock), MU003 (invalid input), MU004 (variant not found).
create or replace function public.crear_venta(
  p_usuario_id uuid,
  p_metodo_pago text,
  p_items jsonb,
  p_cliente_id uuid default null,
  p_idempotency_key text default null
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
  v_total numeric := 0;
  v_total_costo numeric := 0;
begin
  -- Idempotency: a retried request returns the original sale.
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

  select id into v_sesion_id from sesiones_caja where estado = 'abierta' for share;
  if v_sesion_id is null then
    raise exception 'No hay sesión de caja abierta.' using errcode = 'MU001';
  end if;

  begin
    insert into ventas (cliente_id, usuario_id, sesion_caja, total, total_costo, metodo_pago, idempotency_key)
    values (p_cliente_id, p_usuario_id, v_sesion_id, 0, 0, p_metodo_pago, p_idempotency_key)
    returning * into v_venta;
  exception when unique_violation then
    -- A concurrent request with the same idempotency key won the race.
    select * into v_venta from ventas where idempotency_key = p_idempotency_key;
    return v_venta;
  end;

  -- Merge duplicate variants and lock rows in a stable order to avoid deadlocks.
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
     where id = v_item.variante_id;

    insert into venta_detalle (venta_id, variante_id, cantidad, precio_unitario, costo_unitario)
    values (v_venta.id, v_item.variante_id, v_item.cantidad, v_variante.precio_venta, v_variante.precio_costo);

    v_total := v_total + v_item.cantidad * v_variante.precio_venta;
    v_total_costo := v_total_costo + v_item.cantidad * v_variante.precio_costo;
  end loop;

  update ventas
     set total = round(v_total, 2),
         total_costo = round(v_total_costo, 2)
   where id = v_venta.id
  returning * into v_venta;

  return v_venta;
end;
$$;

revoke execute on function public.crear_venta(uuid, text, jsonb, uuid, text) from public, anon, authenticated;
grant execute on function public.crear_venta(uuid, text, jsonb, uuid, text) to service_role;
