-- Data integrity checks (existing data verified to comply).
alter table public.producto_variantes
  add constraint producto_variantes_stock_no_negativo check (stock_actual >= 0),
  add constraint producto_variantes_precio_venta_no_negativo check (precio_venta >= 0),
  add constraint producto_variantes_precio_costo_no_negativo check (precio_costo is null or precio_costo >= 0);

alter table public.venta_detalle
  add constraint venta_detalle_cantidad_positiva check (cantidad > 0),
  add constraint venta_detalle_precio_no_negativo check (precio_unitario >= 0);

alter table public.ventas
  add constraint ventas_total_no_negativo check (total >= 0),
  add constraint ventas_metodo_pago_valido check (metodo_pago in ('Efectivo', 'Tarjeta', 'QR'));

alter table public.movimientos_caja
  add constraint movimientos_caja_monto_positivo check (monto > 0);

alter table public.sesiones_caja
  add constraint sesiones_caja_monto_apertura_no_negativo check (monto_apertura >= 0),
  add constraint sesiones_caja_monto_real_no_negativo check (monto_real_efectivo is null or monto_real_efectivo >= 0);

-- Single global cash register: at most one open session at a time.
create unique index sesiones_caja_una_abierta on public.sesiones_caja ((true)) where estado = 'abierta';

-- Idempotent sale creation.
alter table public.ventas add column idempotency_key text;
create unique index ventas_idempotency_key_key on public.ventas (idempotency_key) where idempotency_key is not null;

-- Indexes for money queries and FKs.
create index ventas_created_at_idx on public.ventas (created_at);
create index ventas_sesion_caja_idx on public.ventas (sesion_caja);
create index ventas_cliente_id_idx on public.ventas (cliente_id);
create index ventas_usuario_id_idx on public.ventas (usuario_id);
create index venta_detalle_venta_id_idx on public.venta_detalle (venta_id);
create index venta_detalle_variante_id_idx on public.venta_detalle (variante_id);
create index movimientos_caja_sesion_id_idx on public.movimientos_caja (sesion_id);
create index sesiones_caja_fecha_apertura_idx on public.sesiones_caja (fecha_apertura);
create index producto_variantes_producto_id_idx on public.producto_variantes (producto_id);
