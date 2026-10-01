from sqlalchemy.orm import Session
from models.user import User
from schemas.requests.user import UserCreate, UserUpdate


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def get_user(self, user_id: int) -> User | None:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_users(self, skip: int = 0, limit: int = 100) -> list[User]:
        return self.db.query(User).offset(skip).limit(limit).all()

    def create_user(self, user_data: UserCreate) -> User:
        existing = self.db.query(User).filter(User.email == user_data.email).first()
        if existing:
            raise ValueError(f"Email {user_data.email} already registered")

        db_user = User(**user_data.model_dump())
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)
        return db_user

    def update_user(self, user_id: int, update_data: UserUpdate) -> User | None:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        for field, value in update_data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        self.db.commit()
        self.db.refresh(user)
        return user

    def delete_user(self, user_id: int) -> bool:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        self.db.delete(user)
        self.db.commit()
        return True