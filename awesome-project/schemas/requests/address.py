from pydantic import BaseModel, EmailStr


class AddressCreate(BaseModel):
    email_address: EmailStr
    user_id: int
