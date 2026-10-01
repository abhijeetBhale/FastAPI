from sqlalchemy.orm import Session
from models.address import Address
from schemas.requests.address import AddressCreate


class AddressService:
    def __init__(self, db: Session):
        self.db = db

    def get_addresses(self, skip: int = 0, limit: int = 100) -> list[Address]:
        return self.db.query(Address).offset(skip).limit(limit).all()

    def get_address(self, address_id: int) -> Address | None:
        return self.db.query(Address).filter(Address.id == address_id).first()

    def create_address(self, addr_data: AddressCreate) -> Address:
        from models.user import User

        user = self.db.query(User).filter(User.id == addr_data.user_id).first()
        if not user:
            raise ValueError(f"User {addr_data.user_id} does not exist")

        db_addr = Address(**addr_data.model_dump())
        self.db.add(db_addr)
        self.db.commit()
        self.db.refresh(db_addr)
        return db_addr

    def delete_address(self, address_id: int) -> bool:
        addr = self.get_address(address_id)
        if not addr:
            return False
        self.db.delete(addr)
        self.db.commit()
        return True