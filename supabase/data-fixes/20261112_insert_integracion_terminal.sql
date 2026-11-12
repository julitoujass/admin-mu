-- Applied manually on 2026-11-12: single settings row of the payment terminal integration.
insert into public.integracion_terminal (id, proveedor, habilitado) values (1, 'fake', false) on conflict (id) do nothing;
