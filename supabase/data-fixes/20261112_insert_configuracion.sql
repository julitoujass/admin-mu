-- Applied manually on 2026-11-12: creates the single business settings row (id = 1).
insert into public.configuracion (id, nombre_negocio, descuento_max_empleado) values (1, 'Mundo Uniforme', 10) on conflict (id) do nothing;
