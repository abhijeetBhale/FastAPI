from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from schemas.requests.user import UserCreate, UserUpdate
from schemas.responses.user import UserDetailResponse, UserListResponse, UserResponse
from services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=UserListResponse, summary="List users")
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, description="Name or email contains"),
    sort: str = Query("id", description="id|name|email|created_at, prefix - to reverse"),
    db: Session = Depends(get_db),
):
    try:
        page = UserService(db).list_users(
            skip=skip, limit=limit, is_active=is_active, search=search, sort=sort
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in page.items],
        total=page.total,
        skip=page.skip,
        limit=page.limit,
        pages=page.pages,
    )


@router.get("/{user_id}", response_model=UserDetailResponse)
def read_user(user_id: int, db: Session = Depends(get_db)):
    svc = UserService(db)
    user = svc.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # A COUNT, not len(user.inspections) — one cheap query either way, but the
    # count does not hydrate every inspection row into memory.
    return UserDetailResponse(
        **UserResponse.model_validate(user).model_dump(),
        inspection_count=svc.get_inspection_count(user_id),
    )


@router.post("/", response_model=UserResponse, status_code=201)
def create_user_endpoint(user_data: UserCreate, db: Session = Depends(get_db)):
    try:
        return UserService(db).create_user(user_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{user_id}", response_model=UserResponse)
def update_user_endpoint(
    user_id: int, update_data: UserUpdate, db: Session = Depends(get_db)
):
    try:
        user = UserService(db).update_user(user_id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/{user_id}", status_code=204, summary="Deactivate (soft delete)")
def delete_user_endpoint(user_id: int, db: Session = Depends(get_db)):
    if not UserService(db).delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")


@router.delete("/{user_id}/purge", status_code=204, summary="Hard delete")
def purge_user_endpoint(user_id: int, db: Session = Depends(get_db)):
    if not UserService(db).hard_delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")


__all__ = ["router"]