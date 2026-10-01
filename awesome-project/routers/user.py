from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db              # ← DB session dependency
from schemas.requests.user import UserCreate, UserUpdate
from schemas.responses.user import UserResponse
from services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/", response_model=List[UserResponse])
def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return UserService(db).get_users(skip, limit)

@router.get("/{user_id}", response_model=UserResponse)
def read_user(user_id: int, db: Session = Depends(get_db)):
    user = UserService(db).get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.post("/", response_model=UserResponse, status_code=201)
def create_user_endpoint(user_data: UserCreate, db: Session = Depends(get_db)):
    try:
        return UserService(db).create_user(user_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{user_id}", response_model=UserResponse)
def update_user_endpoint(user_id: int, update_data: UserUpdate, db: Session = Depends(get_db)):
    user = UserService(db).update_user(user_id, update_data)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.delete("/{user_id}", status_code=204)
def delete_user_endpoint(user_id: int, db: Session = Depends(get_db)):
    success = UserService(db).delete_user(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")   