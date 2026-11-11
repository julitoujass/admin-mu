from app.core.supabase import supabase
from app.schemas.clientes import ClienteCreate, ClienteUpdate

SEARCH_TERM_MAX_LENGTH = 50


def sanitize_search_term(term: str | None) -> str:
    """Reduce a free-text search to letters (incl. accented), digits, spaces and hyphens.

    The term is interpolated into a PostgREST `or=(...)` filter, where characters
    such as `,` `.` `(` `)` `:` `*` `%` are syntax. Anything outside the allowlist
    becomes a space, runs of spaces collapse, and the result is capped in length.
    """
    if not term:
        return ""
    kept = "".join(ch if ch.isalnum() or ch in " -" else " " for ch in term)
    return " ".join(kept.split())[:SEARCH_TERM_MAX_LENGTH].strip()


class ClienteService:
    @staticmethod
    def get_clientes(query: str | None = None, limit: int = 200, offset: int = 0):
        db_query = supabase.table("clientes").select("*")
        term = sanitize_search_term(query)
        if term:
            # Search by name or DNI/CUIT
            db_query = db_query.or_(f"nombre.ilike.%{term}%,dni_cuit.ilike.%{term}%")

        response = db_query.order("nombre").order("id").range(offset, offset + limit - 1).execute()
        return response.data

    @staticmethod
    def create_cliente(cliente: ClienteCreate):
        response = supabase.table("clientes").insert(cliente.model_dump(exclude_none=True)).execute()
        return response.data[0]

    @staticmethod
    def update_cliente(cliente_id: str, update_data: ClienteUpdate):
        response = (
            supabase.table("clientes").update(update_data.model_dump(exclude_unset=True)).eq("id", cliente_id).execute()
        )
        if not response.data:
            return None
        return response.data[0]
