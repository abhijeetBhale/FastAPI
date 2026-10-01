from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from schemas.requests.address import AddressCreate
from schemas.responses.address import AddressResponse
from services.address_service import AddressService

router = APIRouter(prefix="/addresses", tags=["Addresses"])

@router.get("/", response_model=List[AddressResponse])
def read_addresses(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return AddressService(db).get_addresses(skip, limit)

@router.get("/{address_id}", response_model=AddressResponse)
def read_address(address_id: int, db: Session = Depends(get_db)):
    addr = AddressService(db).get_address(address_id)
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")
    return addr

@router.post("/", response_model=AddressResponse, status_code=201)
def create_address_endpoint(addr_data: AddressCreate, db: Session = Depends(get_db)):
    try:
        return AddressService(db).create_address(addr_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{address_id}", status_code=204)
def delete_address_endpoint(address_id: int, db: Session = Depends(get_db)):
    success = AddressService(db).delete_address(address_id)
    if not success:
        raise HTTPException(status_code=404, detail="Address not found")   