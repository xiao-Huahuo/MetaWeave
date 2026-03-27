from datetime import timedelta, datetime

from app.core.database import create_db_and_tables
from app.core.security import get_password_hash
from app.core.config import GlobalConfig
from app.models.user import User
from sqlmodel import Session, select
from app.core.database import engine

def init_db(uname, email, password, phone):

    create_db_and_tables()
    with Session(engine) as session:
        # 检查管理员用户是否已存在
        admin_details = None
        existing_admin = session.exec(
            select(User).where(User.uname == uname)
        ).first()
        if existing_admin:
            admin_details = existing_admin
            print("检测到管理员已存在.")
        else:
            # 创建管理员用户
            admin_user = User(
                uname=uname,
                email=email,
                hashed_pwd=get_password_hash(password),
                phone=phone,
                is_admin=True,
                created_time=datetime.now(),
                last_login=datetime.now()
            )
            session.add(admin_user)
            session.commit()
            session.refresh(admin_user)
            admin_details = admin_user
            print("正在初始化管理员账户...")
        print(f"管理员账户信息:\n==================================\n{admin_details}\nDEBUG | 明文密码: {password}\n==================================")
    return admin_details
