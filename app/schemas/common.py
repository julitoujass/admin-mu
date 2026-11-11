from pydantic import BaseModel


class OkResponse(BaseModel):
    ok: bool = True


class MessageResponse(BaseModel):
    message: str
