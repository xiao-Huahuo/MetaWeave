from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from typing import List, Optional


class UserBase(SQLModel):
    uname: str = Field(index=True)
    email: str = Field(unique=True, index=True)
    phone: Optional[str] = Field(default=None)
    is_admin: bool = Field(default=False)

class User(UserBase, table=True):
    uid: Optional[int] = Field(default=None, primary_key=True)
    hashed_pwd: str
    created_time: datetime = Field(default_factory=datetime.now)
    last_login: datetime = Field(default_factory=datetime.now)

