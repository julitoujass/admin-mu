from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from app.api.auth_deps import get_current_user
from app.schemas.catalogos import MarcaCreate, MarcaUpdate, MarcaResponse, CategoriaCreate, CategoriaUpdate, CategoriaResponse
from app.services.catalogo_service import CatalogoService
from app.services.log_service import LogService
from fastapi.responses import JSONResponse
from app.api.auth_deps import get_current_user
from app.schemas.catalogos import MarcaCreate, MarcaUpdate, MarcaResponse, CategoriaCreate, CategoriaUpdate, CategoriaResponse
from app.services.catalogo_service import CatalogoService

router = APIRouter()

# ============ MARCAS ============

@router.get("/marcas", response_model=List[MarcaResponse])
def get_marcas(_=Depends(get_current_user)):
    return CatalogoService.get_marcas()

@router.post("/marcas", response_model=MarcaResponse)
def create_marca(marca: MarcaCreate, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    try:
        result = CatalogoService.create_marca(marca)
        background_tasks.add_task(
            LogService.registrar_log,
            usuario_id=current_user.id,
            evento="CREATE",
            entidad="marcas",
            entidad_id=str(result["id"]),
            payload_enviado=marca.model_dump(),
            respuesta_recibida=result
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/marcas/{marca_id}", response_model=MarcaResponse)
def update_marca(marca_id: int, marca: MarcaUpdate, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    updated = CatalogoService.update_marca(marca_id, marca)
    if not updated:
        raise HTTPException(status_code=404, detail="Marca no encontrada")
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="UPDATE",
        entidad="marcas",
        entidad_id=str(marca_id),
        payload_enviado=marca.model_dump(exclude_unset=True),
        respuesta_recibida=updated
    )
    return updated

@router.delete("/marcas/{marca_id}")
def delete_marca(marca_id: int, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    try:
        success = CatalogoService.delete_marca(marca_id)
        if not success:
            raise HTTPException(status_code=404, detail="Marca no encontrada")
        background_tasks.add_task(
            LogService.registrar_log,
            usuario_id=current_user.id,
            evento="DELETE",
            entidad="marcas",
            entidad_id=str(marca_id)
        )
        return JSONResponse(content={"message": "Marca eliminada correctamente"})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

# ============ CATEGORIAS ============

@router.get("/categorias", response_model=List[CategoriaResponse])
def get_categorias(_=Depends(get_current_user)):
    return CatalogoService.get_categorias()

@router.post("/categorias", response_model=CategoriaResponse)
def create_categoria(categoria: CategoriaCreate, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    try:
        result = CatalogoService.create_categoria(categoria)
        background_tasks.add_task(
            LogService.registrar_log,
            usuario_id=current_user.id,
            evento="CREATE",
            entidad="categorias",
            entidad_id=str(result["id"]),
            payload_enviado=categoria.model_dump(),
            respuesta_recibida=result
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/categorias/{categoria_id}", response_model=CategoriaResponse)
def update_categoria(categoria_id: int, categoria: CategoriaUpdate, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    updated = CatalogoService.update_categoria(categoria_id, categoria)
    if not updated:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    background_tasks.add_task(
        LogService.registrar_log,
        usuario_id=current_user.id,
        evento="UPDATE",
        entidad="categorias",
        entidad_id=str(categoria_id),
        payload_enviado=categoria.model_dump(exclude_unset=True),
        respuesta_recibida=updated
    )
    return updated

@router.delete("/categorias/{categoria_id}")
def delete_categoria(categoria_id: int, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    try:
        success = CatalogoService.delete_categoria(categoria_id)
        if not success:
            raise HTTPException(status_code=404, detail="Categoría no encontrada")
        background_tasks.add_task(
            LogService.registrar_log,
            usuario_id=current_user.id,
            evento="DELETE",
            entidad="categorias",
            entidad_id=str(categoria_id)
        )
        return JSONResponse(content={"message": "Categoría eliminada correctamente"})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")
