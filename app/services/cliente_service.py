from app.core.supabase import supabase
from app.schemas.clientes import ClienteCreate, ClienteUpdate

class ClienteService:
    @staticmethod
    def get_clientes(query: str | None = None):
        db_query = supabase.table("clientes").select("*")
        if query:
            # Search by name or DNI
            db_query = db_query.or_(f"nombre.ilike.%{query}%,dni_cuit.ilike.%{query}%")
        
        response = db_query.execute()
        return response.data

    @staticmethod
    def create_cliente(cliente: ClienteCreate):
        response = supabase.table("clientes").insert(cliente.model_dump(exclude_none=True)).execute()
        return response.data[0]

    @staticmethod
    def update_cliente(cliente_id: str, update_data: ClienteUpdate):
        response = supabase.table("clientes").update(update_data.model_dump(exclude_unset=True)).eq("id", cliente_id).execute()
        if not response.data:
            return None
        return response.data[0]
