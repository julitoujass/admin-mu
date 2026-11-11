from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.auth_deps import RoleChecker, get_current_user
from app.schemas.catalogos import (
    CategoriaCreate,
    CategoriaResponse,
    CategoriaUpdate,
    MarcaCreate,
    MarcaResponse,
    MarcaUpdate,
)
from app.schemas.common import MessageResponse
from app.services.audit import audit
from app.services.catalogo_service import CatalogoService

router = APIRouter()

# ============ MARCAS ============

@router.get("/marcas", response_model=List[MarcaResponse])
def get_marcas(_=Depends(get_current_user)):
    return CatalogoService.get_marcas()

@router.post("/marcas", response_model=MarcaResponse)
def create_marca(marca: MarcaCreate, background_tasks: BackgroundTasks, current_user=Depends(RoleChecker(["admin"]))):
    result = CatalogoService.create_marca(marca)
    audit(
        background_tasks,
        current_user,
        "CREATE",
        "marcas",
        entidad_id=str(result["id"]),
        payload=marca.model_dump(),
        respuesta=result,
    )
    return result

@router.patch("/marcas/{marca_id}", response_model=MarcaResponse)
def update_marca(marca_id: int, marca: MarcaUpdate, background_tasks: BackgroundTasks, current_user=Depends(RoleChecker(["admin"]))):
    updated = CatalogoService.update_marca(marca_id, marca)
    if not updated:
        raise HTTPException(status_code=404, detail="Marca no encontrada")
    audit(
        background_tasks,
        current_user,
        "UPDATE",
        "marcas",
        entidad_id=str(marca_id),
        payload=marca.model_dump(exclude_unset=True),
        respuesta=updated,
    )
    return updated

@router.delete("/marcas/{marca_id}", response_model=MessageResponse)
def delete_marca(marca_id: int, background_tasks: BackgroundTasks, current_user=Depends(RoleChecker(["admin"]))):
    try:
        success = CatalogoService.delete_marca(marca_id)
        if not success:
            raise HTTPException(status_code=404, detail="Marca no encontrada")
        audit(
            background_tasks,
            current_user,
            "DELETE",
            "marcas",
            entidad_id=str(marca_id),
        )
        return MessageResponse(message="Marca eliminada correctamente")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

# ============ CATEGORIAS ============

@router.get("/categorias", response_model=List[CategoriaResponse])
def get_categorias(_=Depends(get_current_user)):
    return CatalogoService.get_categorias()

@router.post("/categorias", response_model=CategoriaResponse)
def create_categoria(categoria: CategoriaCreate, background_tasks: BackgroundTasks, current_user=Depends(RoleChecker(["admin"]))):
    result = CatalogoService.create_categoria(categoria)
    audit(
        background_tasks,
        current_user,
        "CREATE",
        "categorias",
        entidad_id=str(result["id"]),
        payload=categoria.model_dump(),
        respuesta=result,
    )
    return result

@router.patch("/categorias/{categoria_id}", response_model=CategoriaResponse)
def update_categoria(categoria_id: int, categoria: CategoriaUpdate, background_tasks: BackgroundTasks, current_user=Depends(RoleChecker(["admin"]))):
    updated = CatalogoService.update_categoria(categoria_id, categoria)
    if not updated:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    audit(
        background_tasks,
        current_user,
        "UPDATE",
        "categorias",
        entidad_id=str(categoria_id),
        payload=categoria.model_dump(exclude_unset=True),
        respuesta=updated,
    )
    return updated

@router.delete("/categorias/{categoria_id}", response_model=MessageResponse)
def delete_categoria(categoria_id: int, background_tasks: BackgroundTasks, current_user=Depends(RoleChecker(["admin"]))):
    try:
        success = CatalogoService.delete_categoria(categoria_id)
        if not success:
            raise HTTPException(status_code=404, detail="Categoría no encontrada")
        audit(
            background_tasks,
            current_user,
            "DELETE",
            "categorias",
            entidad_id=str(categoria_id),
        )
        return MessageResponse(message="Categoría eliminada correctamente")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
