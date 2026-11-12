-- Fix the MU007 message in registrar_venta: RAISE parsed '%%%' as a literal % followed by the
-- placeholder ("es %10"). Rewrite that single statement in the live definition.
do $fix$
declare
  v_def text;
  v_old text := $o$raise exception 'El descuento máximo permitido para empleados es %%%', trim(to_char(v_limite, 'FM990D##')) using errcode = 'MU007';$o$;
  v_new text := $n$raise exception using errcode = 'MU007', message = 'El descuento máximo permitido para empleados es ' || trim_scale(v_limite)::text || '%';$n$;
begin
  v_def := pg_get_functiondef('public.registrar_venta(uuid,text,jsonb,uuid,text,text,numeric,text,numeric,boolean)'::regprocedure);
  if position(v_old in v_def) = 0 then
    raise exception 'registrar_venta: expected MU007 statement not found';
  end if;
  execute replace(v_def, v_old, v_new);
end
$fix$;
