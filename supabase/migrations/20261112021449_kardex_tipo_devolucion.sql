-- Allow 'devolucion' entries in the stock ledger (partial returns).
alter table public.movimientos_stock drop constraint movimientos_stock_tipo_check;
alter table public.movimientos_stock add constraint movimientos_stock_tipo_check
  check (tipo in ('venta', 'anulacion', 'ajuste', 'devolucion'));
