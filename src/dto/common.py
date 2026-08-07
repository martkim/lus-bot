from typing import Optional
from pydantic import BaseModel


class MessageResponse(BaseModel):
    """Generic {success, message} envelope used by routes with no payload data."""
    success: bool
    message: Optional[str] = None
