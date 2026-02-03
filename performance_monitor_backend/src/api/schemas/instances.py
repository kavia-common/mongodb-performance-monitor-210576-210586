from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class InstanceBase(BaseModel):
    """Base fields for a MongoDB instance connection record."""

    name: str = Field(..., description="Friendly display name for the instance.")
    host: str = Field(..., description="Hostname or IP address of the MongoDB instance.")
    port: int = Field(27017, ge=1, le=65535, description="MongoDB port number.")
    username: Optional[str] = Field(default=None, description="Optional username for authentication.")
    tls: bool = Field(default=False, description="Whether TLS is enabled for this connection.")
    notes: Optional[str] = Field(default=None, description="Optional notes shown in the UI.")


class InstanceCreate(InstanceBase):
    """Request body for creating an instance."""

    password: Optional[str] = Field(
        default=None,
        description="Optional password (not returned by API). Stub only; will be stored securely later.",
    )


class InstanceUpdate(BaseModel):
    """Request body for updating an instance (partial update)."""

    name: Optional[str] = Field(default=None, description="Friendly display name for the instance.")
    host: Optional[str] = Field(default=None, description="Hostname or IP address.")
    port: Optional[int] = Field(default=None, ge=1, le=65535, description="MongoDB port number.")
    username: Optional[str] = Field(default=None, description="Optional username for authentication.")
    password: Optional[str] = Field(default=None, description="Optional password. Stub only.")
    tls: Optional[bool] = Field(default=None, description="Whether TLS is enabled.")
    notes: Optional[str] = Field(default=None, description="Optional notes shown in the UI.")
    enabled: Optional[bool] = Field(default=None, description="Whether this instance is enabled in monitoring.")


class InstanceOut(InstanceBase):
    """Response model representing an instance."""

    id: str = Field(..., description="Stable instance identifier.")
    enabled: bool = Field(default=True, description="Whether this instance is enabled in monitoring.")
    created_at: datetime = Field(..., description="UTC timestamp when instance was created.")
    updated_at: datetime = Field(..., description="UTC timestamp when instance was last updated.")


class InstanceListResponse(BaseModel):
    """Envelope for listing instances."""

    items: List[InstanceOut] = Field(..., description="List of configured instances.")
    total: int = Field(..., ge=0, description="Total number of instances returned.")

