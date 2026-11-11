-- Cover the remaining unindexed foreign keys reported by the performance advisor.
create index if not exists logs_usuario_id_idx on public.logs (usuario_id);
create index if not exists perfiles_rol_id_idx on public.perfiles (rol_id);
create index if not exists producto_categorias_categoria_id_idx on public.producto_categorias (categoria_id);
create index if not exists productos_marca_id_idx on public.productos (marca_id);
create index if not exists rol_permisos_permiso_id_idx on public.rol_permisos (permiso_id);
create index if not exists sesiones_caja_usuario_id_idx on public.sesiones_caja (usuario_id);
