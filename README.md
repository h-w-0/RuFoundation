<div align="center">
  <h1>RuFoundation</h1>
  <h3>一款由俄罗斯 SCP 分部开发的、兼容 Wikidot 的 Wiki 引擎</h3>
  <h4><a href="https://boosty.to/scpfanpage">#StandWithSCPRU</a></h4>
  <img src="https://i.kym-cdn.com/photos/images/facebook/001/839/765/e80.png" width="300px" alt="scp-ru">
</div>

## 环境要求
注：以下为测试验证过的环境版本，其他版本可能存在兼容性差异
- Windows 10
- PostgreSQL 17.2
- NodeJS v17.3.0
- Python 3.13.2
- Rust 1.63

## PostgreSQL 配置
默认配置信息如下：
- 用户名：`postgress`（环境变量 `POSTGRES_USER`）
- 密码：`zaq123`（环境变量 `POSTGRES_PASSWORD`）
- 数据库名：`scpwiki`（环境变量 `POSTGRES_DB`）
- 数据库地址：`localhost`（环境变量 `DB_PG_HOST`）
- 数据库端口：`5432`（环境变量 `DB_PG_PORT`）

你可以通过上述对应的环境变量修改配置。

## 启动步骤
1.  首先进入 `web/js` 目录，执行命令 `yarn install`
2.  回到项目根目录，依次执行以下命令：
    - `pip install -r requirements.txt`
    - `python manage.py migrate`
    - `python manage.py runserver --watch`

## 创建管理员账户
执行命令 `python manage.py createsuperuser --username Admin --email "" --skip-checks`，然后按照终端提示完成后续操作。

## 数据库初始化
若要正常运行项目，数据库中需要提前创建以下对象：
- 站点记录（适用于本地环境 `localhost`）
- 部分关键页面（如 `nav:top`、`nav:side`），这些页面是保证系统界面正常显示的核心

你可以通过运行以下命令，完成基础数据的初始化配置：
- `python manage.py createsite -s scp-ru -d localhost:8000 -t "SCP Foundation" -H "Russian branch"`
- `python manage.py seed`

## Docker 部署方式

### 环境要求（测试验证版本）
- Docker 28.4.0
- Docker Compose 2.39.4

### 快速上手
启动项目：
执行命令 `docker compose up`

清空所有数据：
依次执行以下命令
- `docker compose down`
- `rm -rf ./files ./archive ./postgresql`

在容器内创建用户、站点并完成数据库初始化：
先启动项目，再执行如下格式的命令：
- `docker exec -it scpdev-web-1 python manage.py createsite -s scp-ru -d localhost -t "SCP Foundation" -H "Russian branch"`
- `docker exec -it scpdev-web-1 seed`

更新正在运行的应用：
执行命令 `docker compose up -d --no-deps --build web`

---

我可以帮你整理这份文档里的**关键命令清单**，方便你部署时直接复制使用，需要吗？
