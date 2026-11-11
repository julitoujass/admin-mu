# Base de datos Supabase

## Estructura

- `migrations/`: migraciones registradas en Supabase. Se aplican mediante la herramienta MCP de Supabase (`apply_migration`). Cada archivo sigue el formato `<version>_<nombre>.sql`.
- `data-fixes/`: correcciones de datos puntuales ejecutadas a mano. No son migraciones y no forman parte del historial de esquema.

## Esquema base pendiente

El esquema base (tablas) se creó desde el dashboard de Supabase antes de que las migraciones se registraran, por eso **no está todavía en este repositorio**. Para incorporarlo hay que extraerlo con la CLI de Supabase y guardarlo como baseline:

```bash
npx supabase login
npx supabase link --project-ref <ref>
npx supabase db pull
```

## Convenciones

- Los cambios de esquema nuevos deben agregarse como migraciones, no como SQL suelto.
- Después de cada cambio de esquema, ejecutar los advisors de seguridad y rendimiento de Supabase (`get_advisors` por MCP o `supabase db advisors` por CLI) y corregir los hallazgos.
