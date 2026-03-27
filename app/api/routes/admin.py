from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.database import get_session
from app.core.security import get_password_hash
from app.models.user import User
from app.schemas.user import UserRead, UserUpdate

router = APIRouter()


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user

# 获取用户列表
@router.get("/users", response_model=List[UserRead])
def get_users(
    uid: Optional[int] = None,
    uname: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
):
    query = select(User)
    if uid:
        query = query.where(User.uid == uid)
    if uname:
        query = query.where(User.uname.ilike(f"%{uname}%"))
    if email:
        query = query.where(User.email.ilike(f"%{email}%"))
    if phone:
        query = query.where(User.phone.ilike(f"%{phone}%"))
    users = session.exec(query).all()
    return users

@router.patch("/users/{uid}", response_model=UserRead)
def update_user(
    uid: int,
    user_update: UserUpdate,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
):
    user = session.get(User, uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    update_data = user_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key == "pwd":
            setattr(user, "hashed_pwd", get_password_hash(value))
        else:
            setattr(user, key, value)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

@router.delete("/users/{uid}")
def delete_user(
    uid: int,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
):
    user = session.get(User, uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.uid == admin.uid:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    session.delete(user)
    session.commit()
    return {"ok": True}
