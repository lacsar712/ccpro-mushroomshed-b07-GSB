# MushroomShed-01 · 菇房出菇台账

食用菌菇房「出菇室环境记录与采收台账」种子项目（非库存 / 电商 / 医院 / 考勤）。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.11 · Flask · SQLAlchemy 2 · Marshmallow · Flask-JWT-Extended · passlib(bcrypt) · gunicorn |
| 前端 | SolidJS · Vite · TypeScript · @solidjs/router |
| 数据库 | MySQL 8（协议兼容原 MariaDB 设计） |
| 部署 | docker-compose · 前端 Nginx 反代 `/api` |

## 端口与账号

| 服务 | 端口 |
| --- | --- |
| 前端 | **3800** |
| 后端 API | **8800** |
| MySQL | **3310** |

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `123456` | admin（场长） |
| `fruiter` | `123456` | fruiter（出菇员） |

数据库：`mushroomshed` / `mushroomshed`，库名 `mushroomshed`。JWT 密钥环境变量 **`JWT_SECRET`**。

## 一键启动

```bash
cd MushroomShed-01
docker compose up --build
```

启动后访问：

- 前端：http://localhost:3800
- 后端健康检查：http://localhost:8800/api/health

后端 entrypoint 流程：等待 MySQL 就绪 → `create_all` 建表 → seed 初始数据 → 启动 gunicorn。

## 功能模块

1. **Auth**：JWT 登录（OAuth2 表单或 JSON），`/api/auth/login`、`/api/auth/me`，`Authorization: Bearer`
2. **Shed 菇房**：`name`、`location`、`notes`
3. **Room 出菇室**：`shedId`、`roomCode`、`species`、`capacityBags`、`status(fruiting|idle|sanitize)`；同菇房 `roomCode` 唯一
4. **ClimateLog 环境记录**：`roomId`、`recordedAt`、`tempC`、`humidityPct`、`co2Ppm`、`notes`；`humidityPct ∈ [1,100]`，否则 **400**
5. **FlushHarvest 采收**：`roomId`、`harvestedAt`、`flushNo(≥1)`、`weightKg`、`grade(A|B|C)`、`operatorName`；`weightKg > 0`，否则 **400**。`weightKg` 永远保存称重原值，接口另返回扣水后的展示公斤 `moistureKg`（见下节）
6. **Dashboard**：`shedTotal`、`fruitingRoomCount`、`climateLast24h`、`harvestKgLast7d`（近 7 日 `moistureKg` 合计）

各实体 API：`GET/POST` 列表与创建、`DELETE` 按 ID 删除；采收与环境记录另支持 `GET/PUT` 按 ID。

## 扣水规则（moistureKg）

- 每条采收取**同室**、`recordedAt ≤ harvestedAt` 且间隔 **≤ 180 分钟**的最近一条 ClimateLog。
- 该记录 `humidityPct ≥ 92`：`moistureKg = weightKg × 0.96`；`85 ≤ humidityPct < 92`：`moistureKg = weightKg`（不扣）。
- 窗口内无环境记录：**409**，正文带 `roomId`；`humidityPct < 85`：**409**，正文带 `climateLogId`。列表与 Dashboard 合计中此类采收行不出现。
- 公式只在后端 `app/moisture.py` 的 `moisture_kg_for_harvest` 实现，采收列表、采收单条、Dashboard 七日公斤三处共用；前端只并排展示 `weightKg` 与 `moistureKg`，不在浏览器里乘系数。
- 修改采收（`PUT /api/flush-harvests/<id>`）会重算，无法扣水则 **409** 且整单不保存；修改环境记录时刻（`PUT /api/climate-logs/<id>`）若把已挂潮次挤出 180 分钟窗口，整单回滚并 **409**，正文 `harvestId` 列出受影响采收。

## 前端页面

Login · Dashboard · Sheds · Rooms · ClimateLogs · FlushHarvests（侧边栏布局）

## 本地开发（可选）

```bash
# 数据库（或用 compose 只起 db）
docker compose up -d db

# 后端
cd backend
pip install -r requirements.txt
set DATABASE_URL=mysql+pymysql://mushroomshed:mushroomshed@localhost:3310/mushroomshed
set JWT_SECRET=local-dev-secret
python -c "from app.database import Base, engine; from app import models; Base.metadata.create_all(bind=engine)"
python -c "from app.seed import seed; seed()"
gunicorn wsgi:app --bind 0.0.0.0:8800 --reload

# 前端
cd frontend
npm install
npm run dev
```

## 目录结构

```
MushroomShed-01/
├── docker-compose.yml
├── README.md
├── .gitignore
├── backend/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── requirements.txt
│   ├── wsgi.py
│   └── app/
│       ├── __init__.py
│       ├── config.py
│       ├── database.py
│       ├── auth.py
│       ├── seed.py
│       ├── utils.py
│       ├── models/
│       ├── schemas/
│       └── routes/
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── pages/
        ├── components/
        └── api/
```
