from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Request, status

from src.api.schemas.common import ErrorResponse
from src.api.schemas.instances import InstanceCreate, InstanceListResponse, InstanceOut, InstanceUpdate
from src.api.services import instances_service

router = APIRouter(prefix="/api/instances", tags=["Instances"])


@router.get(
    "",
    response_model=InstanceListResponse,
    summary="List instances",
    description="Return all configured MongoDB instances (stubbed in-memory).",
    operation_id="list_instances",
)
def list_instances(request: Request) -> InstanceListResponse:
    """List all configured instances."""
    items = instances_service.list_instances(request)
    return InstanceListResponse(items=items, total=len(items))


@router.post(
    "",
    response_model=InstanceOut,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
    summary="Create instance",
    description="Create a new MongoDB instance configuration (stubbed in-memory).",
    operation_id="create_instance",
)
def create_instance(request: Request, payload: InstanceCreate) -> InstanceOut:
    """Create a new instance configuration."""
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty")
    if not payload.host.strip():
        raise HTTPException(status_code=400, detail="host must not be empty")
    return instances_service.create_instance(request, payload)


@router.get(
    "/{instance_id}",
    response_model=InstanceOut,
    responses={404: {"model": ErrorResponse}},
    summary="Get instance",
    description="Fetch a single instance by ID.",
    operation_id="get_instance",
)
def get_instance(request: Request, instance_id: str = Path(..., description="Instance identifier")) -> InstanceOut:
    """Fetch a single instance by ID."""
    inst = instances_service.get_instance(request, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="instance not found")
    return inst


@router.put(
    "/{instance_id}",
    response_model=InstanceOut,
    responses={404: {"model": ErrorResponse}},
    summary="Update instance",
    description="Update an existing instance by ID (partial update supported).",
    operation_id="update_instance",
)
def update_instance(
    request: Request,
    payload: InstanceUpdate,
    instance_id: str = Path(..., description="Instance identifier"),
) -> InstanceOut:
    """Update an instance configuration."""
    inst = instances_service.update_instance(request, instance_id, payload)
    if not inst:
        raise HTTPException(status_code=404, detail="instance not found")
    return inst


@router.delete(
    "/{instance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
    summary="Delete instance",
    description="Delete an instance by ID.",
    operation_id="delete_instance",
)
def delete_instance(request: Request, instance_id: str = Path(..., description="Instance identifier")) -> None:
    """Delete an instance configuration."""
    ok = instances_service.delete_instance(request, instance_id)
    if not ok:
        raise HTTPException(status_code=404, detail="instance not found")
    return None

