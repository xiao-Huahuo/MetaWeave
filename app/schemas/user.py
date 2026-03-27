from datetime import datetime
from typing import Optional

from pydantic import EmailStr, field_validator

from sqlmodel import SQLModel

from app.models.user import UserBase


class UserCreate(UserBase):
    email: EmailStr
    pwd: str

    @field_validator("uname", "pwd")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Field cannot be empty")
        return value.strip()

    @field_validator("email")
    @classmethod
    def _email_strip(cls, value: EmailStr) -> EmailStr:
        return str(value).strip()


class UserRead(UserBase):
    uid: int
    created_time: datetime
    last_login: datetime
    is_admin: bool = False

class UserUpdate(SQLModel):
    uname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    pwd: Optional[str] = None
