-- Atomic manual stock adjustment (positive or negative delta).
-- Raises MU003 (zero delta), MU004 (variant not found), MU002 (would go below zero).
create or replace function public.ajustar_stock(p_variante_id uuid, p_cantidad int)
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

  return v_variante;
end;
$$;

revoke execute on function public.ajustar_stock(uuid, int) from public, anon, authenticated;
grant execute on function public.ajustar_stock(uuid, int) to service_role;
