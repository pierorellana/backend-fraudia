from pydantic import BaseModel


class CatalogItemRead(BaseModel):
    id: str | None = None
    code: str
    name: str
    description: str | None = None
    active: bool = True
