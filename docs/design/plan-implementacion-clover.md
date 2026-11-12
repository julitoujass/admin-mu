# Plan de implementación: cobros con tarjeta y QR (Clover Mini)

> Basado en [integracion-clover.md](integracion-clover.md). Fecha: 2026-11-12.
> Principio rector: **todo lo que no depende de Fiserv se construye ya**, contra un terminal simulado; Clover se enchufa después como un adaptador más.

## Resumen

| Etapa | Qué entrega | Depende de | Esfuerzo estimado |
|---|---|---|---|
| A | Referencia manual del pago (valor inmediato) | Nada | 1 día |
| B | Núcleo: modelo, puerto de terminal, orquestación y UI con terminal simulado | Nada | 4–5 días |
| C | Adaptador Clover + OAuth + página de integración | Cuenta de desarrollador y sandbox | 3–4 días |
| D | Anulaciones y devoluciones contra el terminal | B, C | 2 días |
| E | Cuotas y número de comprobante | Prueba en sandbox | 1 día |
| F | QR | Respuesta de Fiserv | 1–2 días |
| G | Piloto y puesta en producción | C, D | 1 semana de uso real |

Las etapas A y B se pueden hacer **en paralelo** a la gestión con Fiserv.

---

## Etapa A — Referencia manual del pago (sin integración)

**Para qué:** desde hoy, poder conciliar cada venta con tarjeta/QR contra el reporte del Clover. Los mismos campos los va a llenar la integración después.

- **DB:** migración que agrega a `ventas` las columnas `pago_proveedor` (`'manual'|'clover'`), `pago_referencia` (código de autorización), `pago_ultimos4`, `pago_marca` y `pago_cuotas`, con CHECKs de formato (4 dígitos, cuotas 1..99). `registrar_venta` acepta esos datos opcionales (nuevo parámetro con default; como cambiar la firma crea una sobrecarga, se publica como `registrar_venta` v2 con nombre nuevo y el backend pasa a usarla).
- **Backend:** `VentaCreate` acepta `pago_referencia`, `pago_ultimos4`, `pago_marca`, `pago_cuotas` (solo si `metodo_pago` ≠ Efectivo). Se devuelven en el detalle y en el historial.
- **Frontend:** en el checkout, con Tarjeta/QR aparecen campos opcionales "Cód. autorización", "Últimos 4", "Cuotas". Se muestran en el detalle, el ticket y el CSV del historial.
- **Listo cuando:** se registra una venta con referencia, aparece en detalle/ticket/CSV y los tests cubren validaciones.

---

## Etapa B — Núcleo con terminal simulado

### B1. Puerto de terminal (arquitectura hexagonal)

`app/integrations/payment_terminal/`:

```python
class PaymentTerminal(Protocol):
    def ping(self) -> bool: ...
    def status(self) -> TerminalStatus: ...                      # IDLE | BUSY | WAITING_FOR_CUSTOMER | UNKNOWN
    def charge(self, req: ChargeRequest) -> ChargeResult: ...     # blocking, up to ~135 s
    def find_by_external_id(self, external_id: str) -> ChargeResult | None: ...
    def cancel_current(self) -> None: ...
    def refund(self, payment_id: str, amount_cents: int | None) -> RefundResult: ...  # None = full refund
    def show_welcome(self) -> None: ...
```

- `ChargeResult.outcome`: `APPROVED | DECLINED | CANCELLED | UNKNOWN` (UNKNOWN = timeout, 500, 504, red).
- Errores tipados: `TerminalBusy` (503), `TerminalUnavailable`, `TerminalBadRequest` (400).
- `FakeTerminal` configurable (aprobar, rechazar, demorar, timeout, ocupado) para tests y para desarrollar la UI sin dispositivo.
- La elección del adaptador sale de la configuración (`PAYMENT_TERMINAL=fake|clover`).

### B2. Base de datos (una migración)

- Tabla `pagos_externos` (ver diseño, sección 5) + índice único parcial que garantiza **un solo cobro activo**: `on pagos_externos ((true)) where estado in ('pendiente','enviado','indeterminado')`.
- Tabla `integracion_clover` (fila única).
- `ventas.pago_externo_id` (FK).
- `cotizar_venta(...)`: el mismo cálculo que `registrar_venta` sin escribir (precios, descuento, recargo, tope del empleado, stock, caja abierta).
- `registrar_venta_con_pago(...)`: igual que `registrar_venta` pero con `p_total_esperado` (falla con **MU011** si difiere), `p_pago_externo_id` y los datos de la tarjeta. Usa el id del pago como clave de idempotencia.
- RLS + permisos solo `service_role`. Prueba en transacción revertida, como en las fases anteriores.

### B3. Orquestación (`app/services/pago_service.py`)

1. `iniciar_cobro(carrito, metodo, usuario)`: cotiza → inserta `pendiente` con el carrito y `external_payment_id` (≤ 32) → agenda la tarea → devuelve `{pago_id, total}`. Si ya hay un cobro activo: 409.
2. `ejecutar_cobro(pago_id)` (tarea en segundo plano): `enviado` → `terminal.charge` → según resultado: `aprobado` → `registrar_venta_con_pago` → `venta_registrada`; si falla → `error_registro` → `terminal.refund` (total) → `reembolsado`. `DECLINED`/`CANCELLED` → `rechazado`/`cancelado`. `UNKNOWN` → `indeterminado`. Siempre `show_welcome` al final.
3. `conciliar_pendientes()`: cada 30 s (tarea del `lifespan` de FastAPI), toma los `indeterminado`, consulta `find_by_external_id` con espera creciente (mínimo 3 intentos) y resuelve. Después de N intentos sin respuesta, queda para revisión manual.
4. Cada transición actualiza `updated_at` y deja auditoría (`CHARGE_STARTED`, `CHARGE_APPROVED`, `CHARGE_FAILED`, `CHARGE_UNKNOWN`, `REFUND_DONE`).
5. Transiciones con `update ... where estado = <esperado>` para que dos procesos no pisen el mismo pago.

### B4. Endpoints (`app/api/v1/endpoints/pagos.py`)

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| POST | `/pagos/terminal` | cualquier usuario activo | Inicia el cobro (mismo body que `POST /ventas/` + `metodo_pago` Tarjeta/QR). 202 |
| GET | `/pagos/{id}` | quien lo inició o admin | Estado, total, datos de tarjeta, `venta_id` |
| POST | `/pagos/{id}/cancelar` | quien lo inició o admin | Cancela en el dispositivo |
| GET | `/pagos/?estado=` | admin | Pagos para revisar (indeterminado, error_registro) |
| POST | `/pagos/{id}/conciliar` | admin | Fuerza la conciliación de uno |
| GET | `/integraciones/terminal/estado` | cualquier usuario activo | `{habilitado, conectado, estado}` para que el POS decida el flujo |

### B5. Frontend (`pos-mu/src/features/pagos/`)

- `api.ts`, `types.ts`, hook `useTerminalPayment(pagoId)` con polling de 1 s (se detiene en estados finales; tope de 3 min con mensaje).
- `PaymentWaitingModal` (`dismissible={false}`): "Esperando pago en el Clover…", total, botón "Cancelar"; estados de éxito, rechazo, "Verificando el pago…" e "Hubo un problema, el cobro se reembolsó".
- Checkout: si `metodo` es Tarjeta/QR **y** la integración está habilitada, "Cobrar" usa este flujo; si no, el actual con referencia manual (Etapa A).
- Página admin "Pagos a revisar" con reintento de conciliación.
- Al aprobar: mismo aviso que hoy con "Imprimir ticket"; el ticket muestra marca, últimos 4, autorización y cuotas.

### B6. Tests

- **Backend:** unitarios del servicio con `FakeTerminal` cubriendo aprobado, rechazado, cancelado, ocupado, timeout → conciliación, error al registrar → reembolso, doble inicio (409), idempotencia (la tarea corre dos veces y hay una sola venta).
- **DB:** `cotizar_venta`, MU011, índice de cobro único.
- **Frontend:** hook de polling (timers falsos), modal por estado, checkout elige el flujo correcto.
- **Listo cuando:** con `PAYMENT_TERMINAL=fake` se puede vender con "tarjeta" de punta a punta en el navegador, incluidos los casos de error.

---

## Etapa C — Adaptador Clover

**Prerrequisitos (fuera del código):** cuenta en el portal de desarrolladores de Clover con 2FA, comercio de prueba en sandbox, app configurada para semi-integración REST, y un Clover de desarrollo o el del local habilitado para pruebas.

- `CloverCloudTerminal(PaymentTerminal)` con `httpx`: base URL según entorno, headers (`Authorization`, `X-Clover-Device-Id`, `X-POS-Id`, `User-Agent`, `Idempotency-Key` en POST), `X-Clover-Timeout` por operación y mapeo de códigos (200, 209, 400, 503, 504, 500) al resultado del puerto. Montos en centavos.
- **OAuth v2:** endpoints `GET /integraciones/clover/conectar` (redirige a Clover) y `GET /integraciones/clover/callback` (canjea el código). Tokens cifrados con `cryptography` (Fernet, nueva dependencia fijada) usando `CLOVER_TOKEN_KEY`. Renovación con la fila bloqueada (`for update`) porque el refresh token es de un solo uso; si falla, la integración se deshabilita y la UI pide reconectar.
- **Frontend:** página admin "Integraciones → Clover": conectar, serie del dispositivo, id de POS, "Probar conexión" (ping + estado), habilitar/deshabilitar.
- **Tests:** unitarios del adaptador con respuestas HTTP simuladas (`httpx.MockTransport`); suite opcional `pytest -m clover_sandbox` contra el sandbox, excluida de CI.
- **Listo cuando:** en sandbox, un cobro aprobado, uno rechazado y uno cancelado en el dispositivo se reflejan bien en el POS, y un corte de red simulado termina conciliado sin doble cobro.

---

## Etapa D — Anulaciones y devoluciones con el terminal

- `cotizar_devolucion(venta_id, items)`: monto proporcional sin escribir.
- Anular venta con `pago_externo_id`: `terminal.refund(total)` → con éxito, `anular_venta`. Devolución parcial: `terminal.refund(monto)` → `registrar_devolucion`. Si el reembolso queda indeterminado, se registra en `pagos_externos` y lo resuelve la conciliación.
- Frontend: "Reembolsando en el Clover…" en los diálogos de anular/devolver; errores con el `detail`.
- **Listo cuando:** en sandbox se anula una venta y se devuelve parte de otra, y el reporte de Clover coincide con el del POS.

---

## Etapa E — Cuotas y comprobante

- Probar en sandbox si `POST /v1/payments` acepta `regionalExtras.argentina.numInstallments` e `invoiceNumber`, y dónde vuelven en la respuesta.
- Si funciona: selector de cuotas en el checkout (solo Tarjeta), se guardan en `ventas.pago_cuotas` y salen en el ticket.
- Si no: el Mini pregunta las cuotas en su pantalla y se leen de la respuesta; si tampoco vienen, se cargan a mano (campo de la Etapa A).

---

## Etapa F — QR

Depende de cómo responda Fiserv (pregunta 3 del diseño):

- **Si "Pagos QR" corre dentro del mismo cobro** (`entryType = QR_CODE`): no hay trabajo extra más que mostrarlo distinto en la UI y en el ticket.
- **Si es una app aparte sin API:** el QR sigue con referencia manual (Etapa A). Se documenta en el instructivo del cajero.
- **Si tiene su propia API:** nuevo adaptador detrás del mismo puerto `PaymentTerminal` (por eso el puerto no habla de "tarjeta").

---

## Etapa G — Piloto y puesta en producción

1. Credenciales de producción, URL de producción LATAM y serie del Mini del local en `.env` y en la página de integración.
2. Integración **deshabilitada** por defecto; se habilita un día con poco movimiento.
3. Al cierre de cada día del piloto: comparar ventas Tarjeta/QR del POS contra el reporte del Clover (monto, cantidad, autorizaciones). Revisar "Pagos a revisar" = vacío.
4. **Runbook** (en `docs/`): qué hacer si el Clover cobró y el POS no registró, si el dispositivo no responde, si hay que reconectar OAuth, y cómo volver al modo manual (deshabilitar la integración) sin perder ventas.
5. Criterio para dar por terminado: una semana sin diferencias entre el POS y el Clover.

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Cobro aprobado sin venta registrada | Reembolso automático + conciliación + pantalla de revisión + runbook |
| Doble cobro por reintento | Nunca reintentar con resultado desconocido; `externalPaymentId` + `Idempotency-Key`; un cobro activo a la vez |
| Precios o stock cambian durante el cobro | `p_total_esperado` (MU011) → reembolso |
| Refresh token gastado o vencido | Renovación con bloqueo de fila; si falla, deshabilitar y pedir reconexión; modo manual como respaldo |
| Varios workers de uvicorn | Estado en la base, transiciones condicionales y conciliación idempotente |
| La doc de Clover cambia o se contradice | Puerto `PaymentTerminal` aísla el resto del sistema; suite de sandbox antes de cada cambio |

## Orden de trabajo sugerido

1. Mandar a Fiserv las preguntas del diseño y crear la cuenta de desarrollador (en paralelo con lo siguiente).
2. Etapa A (rama propia, se puede usar en el local enseguida).
3. Etapa B completa con `FakeTerminal`.
4. Etapa C apenas haya sandbox; luego D y E.
5. Etapa F según la respuesta de Fiserv.
6. Etapa G.
