from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi import Request
from app.core.config import GlobalConfig
from app.api.routes import user, login,admin
from app.core.cors import CorsMiddleWare
from app.db.db_init import init_db
# 定义生命周期管理器
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(
        uname=GlobalConfig.ADMIN_USERNAME if GlobalConfig.ADMIN_USERNAME else GlobalConfig.DEFAULT_ADMIN_USERNAME,
        email=GlobalConfig.ADMIN_EMAIL if GlobalConfig.ADMIN_EMAIL else GlobalConfig.DEFAULT_ADMIN_EMAIL,
        password=GlobalConfig.ADMIN_PASSWORD if GlobalConfig.ADMIN_PASSWORD else GlobalConfig.DEFAULT_ADMIN_PASSWORD,
        phone=GlobalConfig.ADMIN_PHONE if GlobalConfig.ADMIN_PHONE else GlobalConfig.DEFAULT_ADMIN_PHONE
    )
    yield

# 将 lifespan 传入 FastAPI
app = FastAPI(lifespan=lifespan)

# 配置 CORS
app=CorsMiddleWare(app).add_cors_middleware(
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.middleware("http")
async def log_request_middleware(request: Request, call_next):
    response = await call_next(request)
    return response

# 注入路由
app.include_router(user.router, prefix="/user", tags=["user"])
app.include_router(login.router, prefix="/login", tags=["login"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])

if __name__ == "__main__":
    import uvicorn
    # 传app,且reload=True(热重载),改代码后可以直接改后端,无需重启
    uvicorn.run("app.main:app", host=GlobalConfig.HOST, port=GlobalConfig.PORT, reload=True, timeout_keep_alive=60)

