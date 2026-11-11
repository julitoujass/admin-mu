-- Enable RLS on every public table. No policies: only service_role (backend) bypasses RLS.
alter table public.categorias enable row level security;
alter table public.productos enable row level security;
alter table public.producto_categorias enable row level security;
alter table public.producto_variantes enable row level security;
alter table public.marcas enable row level security;
alter table public.clientes enable row level security;
alter table public.logs enable row level security;
alter table public.ventas enable row level security;
alter table public.venta_detalle enable row level security;
alter table public.roles enable row level security;
alter table public.perfiles enable row level security;
alter table public.permisos enable row level security;
alter table public.rol_permisos enable row level security;
alter table public.sesiones_caja enable row level security;
alter table public.movimientos_caja enable row level security;

-- Remove Data API access for public roles (defense in depth).
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;

-- Keep backend access explicit.
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;

-- New objects created by postgres in public do not get public-role grants.
alter default privileges for role postgres in schema public revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public revoke execute on functions from public, anon, authenticated;
