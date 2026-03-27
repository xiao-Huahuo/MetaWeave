# 项目运行与部署方法
## 环境准备
1. 安装 Node.js 和 npm
   - 访问 [Node.js 官网](https://nodejs.org/) 下载并安装最新的 LTS 版本。
   - 安装完成后，打开终端，输入以下命令验证安装：
     ```bash
     node -v
     npm -v
     ```
2. 安装 Python 和 pip 
   - 访问 [Python 官网](https://www.python.org/) 下载并安装最新的 Python 3.x 版本。
   - 安装完成后，打开终端，输入以下命令验证安装：
     ```bash
     python --version
     pip --version
     ```
3. 安装 Docker 和 Docker Compose
   - 访问 [Docker 官网](https://www.docker.com/) 下载并安装 Docker Desktop。
     - 安装完成后，打开终端，输入以下命令验证安装：
       ```bash
       docker --version
       docker-compose --version
       ```

## 开发阶段项目运行方法
1. 开启后端服务:
    在项目根目录中,执行以下命令启动后端服务:
    ```bash
    uvicorn app.main:app --host
    ```
    后端服务默认监听在 http://localhost:8080。
2. 开启前端服务:
    在项目根目录中,执行以下命令启动前端:
    ```bash
    cd web
    npm install --verbose
    npm run dev
    ```
    前端服务默认监听在 http://localhost:5173。

## 生产环境部署方法
在项目根目录中,执行以下命令使用 Docker Compose 启动生产环境:
```bash
docker-compose up -d --build
```
生产环境默认监听在 http://localhost:80。
注: 生产环境下,需要将docker-compose.yml中的相应环境变量的值改为真实的域名或者公网IP,以便于外部访问,如:
```yml
PUBLIC_BASE_URL: http://10.133.130.115:8080 # 部署环境写本机局域网IP, 生产环境这个必须是真实域名/公网IP
FRONTEND_BASE_URL: http://10.133.130.115:5173 # 部署环境写本机局域网IP
```