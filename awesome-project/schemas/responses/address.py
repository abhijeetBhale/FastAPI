from pydantic import BaseModel


class AddressResponse(BaseModel):
    id: int
    email_address: str
    user_id: int

    model_config = {"from_attributes": True}
