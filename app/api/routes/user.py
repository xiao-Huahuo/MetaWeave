from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.core.database import get_session
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.core.security import get_password_hash
from app.api.deps import get_current_user

# 创建路由
router = APIRouter()

# 用户注册
@router.post("/", response_model=UserRead)
def create_user(user: UserCreate, session: Session = Depends(get_session)):
    """
    创建新用户
    :param user:
    :param session:
    :return:
    """
    existing_email = session.exec(select(User).where(User.email == user.email)).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="该邮箱已被注册")

    existing_name = session.exec(select(User).where(User.uname == user.uname)).first()
    if existing_name:
        raise HTTPException(status_code=400, detail="该用户名已存在")

    hashed_pwd = get_password_hash(user.pwd)

    db_user = User.model_validate(
        user,
        update={
            "hashed_pwd": hashed_pwd,
        },
    )

    session.add(db_user)
    session.commit()
    session.refresh(db_user)

    return db_user


# 查询个人信息
@router.get("/me", response_model=UserRead)
def get_user(current_user: User = Depends(get_current_user)):
    """
    获取当前登录用户的个人信息
    :param current_user:
    :return:
    """
    return current_user


# 修改个人信息(部分更新)
@router.patch("/me", response_model=UserRead)
def update_user(
    user_in: UserUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    更新当前登录用户的个人信息
    :param user_in:
    :param session:
    :param current_user:
    :return:
    """
    # 1. 提取需要更新的数据字段(排除未设置字段)
    update_data = user_in.model_dump(exclude_unset=True)

    # 2. 如果包含密码，需要特殊处理
    if "pwd" in update_data:
        # 加密新密码
        hashed_password = get_password_hash(update_data["pwd"])
        # 移除明文并添加哈希值
        del update_data["pwd"]
        update_data["hashed_pwd"] = hashed_password

    # 3. 根据字典更新当前用户对象
    current_user.sqlmodel_update(update_data)

    # 4. 保存到数据库
    session.add(current_user)
    session.commit()
    session.refresh(current_user)

    # 5. 返回更新后的用户
    return current_user