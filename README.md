# style-rotation

这是一个风格轮动单页应用仓库，当前已包含一套可运行的后端与前端实现，并继续以规格文档和黄金样例作为约束来源。

## 仓库用途

本仓库由实现代码和规格文档共同组成：

- `backend/`：FastAPI + SQLAlchemy + pandas 后端
- `frontend/`：Vue 3 + ECharts 单页前端
- `STYLE_ROTATION_REWRITE_SPEC.md`：主规格文档，定义接口、数据表、计算流程和返回契约
- `STYLE_ROTATION_GOLDEN_TEST.md`：黄金测试样例，用于验证 pandas 计算结果和信号生成顺序
- `AGENTS.md`：贡献规范，说明代码、测试和文档维护要求

## 项目目标

最终应用应完成这几个最小闭环：

1. 选择两个指数或 ETF
2. 同步或读取历史行情
3. 计算风格轮动指标
4. 在单页前端展示三联图和信号点

明确不做的内容：

- 登录与权限
- OAuth
- 用户体系
- 后台管理
- 定时任务
- 多页面系统

## 强约束

- 必须支持任意两个标的组合，不能把逻辑写死成固定两只
- 后端至少提供 `GET /api/instruments`、`POST /api/market-data/sync`、`GET /api/style-rotation`
- 数据库至少包含 `instruments` 和 `daily_prices`
- `daily_prices` 必须以 `symbol + trade_date` 唯一
- `GET /api/style-rotation` 的字段、计算顺序、默认参数必须严格遵守规格文档
- 如果规格文档和实现理解出现冲突，优先以黄金测试样例校验结果为准

## 当前技术栈

- 后端：FastAPI + SQLAlchemy + SQLite + pandas
- 前端：Vue 3 + ECharts

数据库默认使用 `data/style_rotation.db`，首次启动时会自动建表并写入演示数据。
`POST /api/market-data/sync` 当前仅保留 `source=tencent` 作为真实同步来源。使用真实同步时，运行环境需要具备可访问相关上游站点的外网能力。

## 本地运行

先启动后端：

```bash
uvicorn backend.app.main:app --reload
```

再启动前端：

```bash
cd frontend
npm install
npm run dev
```

前端默认访问 `http://127.0.0.1:8000`。

## 测试与构建

后端单元测试：

```bash
python -m unittest discover -s backend/tests -v
```

前端生产构建：

```bash
cd frontend
npm run build
```

## 开发顺序

1. 先实现后端项目结构和数据模型
2. 完成三个接口
3. 实现风格轮动计算函数
4. 用黄金测试样例逐项验证输出
5. 在结果稳定后再补前端单页
6. 最后联调

## 开发前先读

修改核心算法或接口契约前，先完整阅读以下两份文档：

1. `STYLE_ROTATION_REWRITE_SPEC.md`
2. `STYLE_ROTATION_GOLDEN_TEST.md`

如果后续调整接口、默认参数或计算顺序，请同步更新代码、`README.md`、`AGENTS.md` 和两份规格文档，避免实现与说明脱节。
