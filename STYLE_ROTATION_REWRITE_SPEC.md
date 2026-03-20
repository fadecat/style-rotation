# 风格轮动单页应用重写规格

## 目标

从零重写一个单页应用，只做一件事：

1. 选择两个指数或 ETF
2. 获取历史行情数据
3. 计算风格轮动指标
4. 返回给前端单页展示

不需要：

- 登录
- OAuth
- 用户体系
- 菜单权限
- 后台管理
- 定时任务

## 核心约束

这个应用必须支持任意两个标的做对比，不能把逻辑写死成某一对固定指数。

必须支持：

- `A:B`
- `C:D`
- `A:D`

这类任意组合。

例如：

- `399376 : 399373`
- `159915 : 510300`
- `588000 : 512100`

都应该走完全相同的接口和计算逻辑。

实现约束：

1. 标的代码必须来自请求参数或数据库配置
2. 后端计算逻辑必须使用 `left_symbol/right_symbol` 泛化实现
3. 前端页面必须允许用户自由选择左右标的
4. 默认组合可以有，但只能是默认值，不能写死在算法里

## 现有老项目里的参考实现

当前老项目对应接口：

- `GET /api/quant/style-rotation`

当前老项目核心代码位置：

- `backend/app/api/quant.py`
- `frontend/src/views/quant/StyleRotation.vue`

新项目不建议沿用这个路由层级，建议直接重写成更轻的接口。

强烈建议配合下面这份校验文档一起使用：

- `STYLE_ROTATION_GOLDEN_TEST.md`

## 新项目推荐接口设计

### 接口 0：获取可选标的列表

用途：为前端下拉框提供可选指数或 ETF。

推荐地址：

- `GET /api/instruments`

查询参数建议：

- `asset_type`: 可选，`INDEX` 或 `ETF`
- `keyword`: 可选，代码或名称模糊搜索
- `is_active`: 可选，默认 `true`

返回示例：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "symbol": "399376",
        "name": "国证小盘成长",
        "market": "CN",
        "asset_type": "INDEX"
      },
      {
        "symbol": "399373",
        "name": "国证大盘价值",
        "market": "CN",
        "asset_type": "INDEX"
      },
      {
        "symbol": "510300",
        "name": "沪深300ETF",
        "market": "CN",
        "asset_type": "ETF"
      }
    ]
  }
}
```

### 接口 1：同步或补齐行情数据

用途：从数据源拉取两个标的的日线数据并入库。

推荐地址：

- `POST /api/market-data/sync`

请求体示例：

```json
{
  "symbols": [
    {
      "symbol": "399376",
      "name": "国证小盘成长",
      "market": "CN",
      "asset_type": "INDEX"
    },
    {
      "symbol": "399373",
      "name": "国证大盘价值",
      "market": "CN",
      "asset_type": "INDEX"
    }
  ],
  "source": "eastmoney",
  "start_date": "2018-01-01",
  "end_date": "2026-03-20"
}
```

返回字段建议：

```json
{
  "code": 200,
  "message": "sync success",
  "data": {
    "source": "eastmoney",
    "items": [
      {
        "symbol": "399376",
        "inserted": 1820,
        "updated": 0,
        "range": {
          "start_date": "2018-01-01",
          "end_date": "2026-03-20"
        }
      },
      {
        "symbol": "399373",
        "inserted": 1820,
        "updated": 0,
        "range": {
          "start_date": "2018-01-01",
          "end_date": "2026-03-20"
        }
      }
    ]
  }
}
```

### 接口 2：计算风格轮动结果

用途：读取数据库里的行情数据，计算指标并返回给前端页面。

推荐地址：

- `GET /api/style-rotation`

查询参数：

- `left_symbol`: 左侧标的，默认 `399376`
- `right_symbol`: 右侧标的，默认 `399373`
- `start_date`: 页面展示起始日期，可选
- `end_date`: 页面展示结束日期，可选
- `return_window`: 滚动收益窗口，默认 `250`
- `ma_window`: 均线窗口，默认 `20`
- `quantile_window_min`: 动态分位数最小样本，默认 `20`

请求示例：

```http
GET /api/style-rotation?left_symbol=399376&right_symbol=399373&start_date=2024-01-01&end_date=2026-03-20
```

强约束：

- `left_symbol` 和 `right_symbol` 必须来自前端选择
- 后端不得在内部偷偷替换成固定代码
- 只要数据库中有这两个标的的历史数据，就必须支持计算
- 如果 `left_symbol == right_symbol`，建议直接返回 `400`

返回字段建议：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "meta": {
      "left_symbol": "399376",
      "right_symbol": "399373",
      "left_name": "国证小盘成长",
      "right_name": "国证大盘价值",
      "return_window": 250,
      "ma_window": 20,
      "start_date": "2024-01-01",
      "end_date": "2026-03-20"
    },
    "series": {
      "dates": ["2024-01-02", "2024-01-03"],
      "left_close": [5234.12, 5250.88],
      "right_close": [6120.55, 6112.01],
      "left_return": [12.31, 12.85],
      "right_return": [5.92, 5.67],
      "spread": [6.39, 7.18],
      "ma": [5.88, 6.01],
      "p90_dynamic": [10.25, 10.25],
      "p10_dynamic": [-4.91, -4.91],
      "left_nav": [1.0, 1.0032],
      "right_nav": [1.0, 0.9986]
    },
    "summary": {
      "latest_spread": 7.18,
      "latest_ma": 6.01,
      "latest_left_return": 12.85,
      "latest_right_return": 5.67,
      "global_p90": 10.43,
      "global_p10": -5.02,
      "signal_count": 6,
      "latest_signal": "none"
    },
    "signals": [
      {
        "date": "2024-03-15",
        "type": "sell",
        "spread": 9.12
      },
      {
        "date": "2024-08-20",
        "type": "buy",
        "spread": -2.44
      }
    ]
  }
}
```

## 后端接口逻辑

### `/api/market-data/sync` 逻辑

1. 接收两个或多个标的代码
2. 根据数据源调用外部行情接口
3. 将返回日线标准化成统一字段
4. 按 `symbol + trade_date` 做 upsert 或忽略重复
5. 返回每个标的新增条数和日期范围

建议只支持日线，不做分钟线。

### `/api/style-rotation` 逻辑

1. 接收两个标的代码和展示区间
2. 为了计算滚动收益，需要向前额外读取一段预热数据
3. 从数据库查询两个标的的日线收盘价
4. 按交易日对齐
5. 计算滚动收益率
6. 计算收益价差
7. 计算均线和动态分位数
8. 生成买卖信号
9. 对最终展示区间重算归一化净值
10. 返回图表序列和摘要信息

## 最小数据库表设计

新项目建议只保留 2 张表。

### 表 1：`instruments`

用途：保存标的信息，便于页面选择。

字段建议：

| 字段名 | 类型 | 说明 |
|---|---|---|
| `id` | bigint pk | 主键 |
| `symbol` | varchar(32) unique | 标的代码 |
| `name` | varchar(128) | 名称 |
| `market` | varchar(16) | 市场，例如 `CN` |
| `asset_type` | varchar(16) | `INDEX` 或 `ETF` |
| `source` | varchar(32) | 默认数据源 |
| `is_active` | boolean | 是否启用 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### 表 2：`daily_prices`

用途：保存标准化后的日线行情。

字段建议：

| 字段名 | 类型 | 说明 |
|---|---|---|
| `id` | bigint pk | 主键 |
| `symbol` | varchar(32) | 标的代码 |
| `trade_date` | date | 交易日 |
| `open` | decimal(18,4) null | 开盘价 |
| `high` | decimal(18,4) null | 最高价 |
| `low` | decimal(18,4) null | 最低价 |
| `close` | decimal(18,4) not null | 收盘价 |
| `volume` | decimal(20,2) null | 成交量 |
| `amount` | decimal(20,2) null | 成交额 |
| `source` | varchar(32) | 数据来源 |
| `raw_payload` | text null | 原始数据 JSON，可选 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

唯一索引建议：

- `uniq_symbol_trade_date (symbol, trade_date)`

查询索引建议：

- `idx_symbol_trade_date (symbol, trade_date)`

## 可选的预设组合设计

如果你希望页面除了自由选择，还能提供几个一键切换组合，可以额外增加一张可选表。

这张表不是必须的。

### 可选表 3：`comparison_presets`

字段建议：

| 字段名 | 类型 | 说明 |
|---|---|---|
| `id` | bigint pk | 主键 |
| `code` | varchar(64) unique | 预设代码 |
| `name` | varchar(128) | 预设名称 |
| `left_symbol` | varchar(32) | 左侧标的 |
| `right_symbol` | varchar(32) | 右侧标的 |
| `sort_order` | int | 排序 |
| `is_active` | boolean | 是否启用 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

说明：

- 预设组合只是前端快捷入口
- 实际分析能力仍然必须支持任意两只标的组合
- 不能因为有预设表，就把接口限制成只能查预设

## 为什么只需要这两张表

风格轮动计算真正用到的核心字段只有：

- `symbol`
- `trade_date`
- `close`

其他字段主要是为了保留扩展空间和排查数据问题，不是策略必须条件。

## 数据获取与标准化规则

无论你后面选 AkShare、Eastmoney、Tushare 还是别的源，入库前都要统一成：

```json
{
  "symbol": "399376",
  "trade_date": "2026-03-20",
  "open": 5231.10,
  "high": 5278.32,
  "low": 5218.08,
  "close": 5250.88,
  "volume": 123456789,
  "amount": 3456789012.15,
  "source": "eastmoney"
}
```

统一规则：

1. 日期统一成 `YYYY-MM-DD`
2. 标的代码统一成无前缀形式，例如 `399376`
3. 价格全部转成数值
4. 按 `trade_date` 升序存储

如果未来支持的是指数、ETF、LOF 等不同资产，算法层不应该分叉。

计算层统一按：

- 左侧标的收盘价序列
- 右侧标的收盘价序列

做同一套处理即可。

## 核心计算逻辑

以下是新项目最重要的部分，AI 写代码时应严格按这个规则实现。

## pandas 参考实现约束

如果你的目标不是“逻辑近似”，而是“尽量复刻现有结果”，那新 AI 不应该自由发挥 DataFrame 处理顺序，必须尽量按下面的 pandas 流程实现。

### 参考处理顺序

```python
import pandas as pd

RETURN_WINDOW = 250
MA_WINDOW = 20
QUANTILE_WINDOW_MIN = 20


def calc_style_rotation(df_left: pd.DataFrame, df_right: pd.DataFrame,
                        start_date: str | None = None,
                        end_date: str | None = None) -> dict:
    # df_left columns: trade_date, close
    # df_right columns: trade_date, close

    df_left = df_left.copy()
    df_right = df_right.copy()

    # 1. 日期转 datetime
    df_left["trade_date"] = pd.to_datetime(df_left["trade_date"])
    df_right["trade_date"] = pd.to_datetime(df_right["trade_date"])

    # 2. 收盘价强制转 float
    df_left["close"] = df_left["close"].astype(float)
    df_right["close"] = df_right["close"].astype(float)

    # 3. 各自按日期排序
    df_left = df_left.sort_values("trade_date").reset_index(drop=True)
    df_right = df_right.sort_values("trade_date").reset_index(drop=True)

    # 4. 以内连接按交易日对齐
    df = pd.merge(
        df_left[["trade_date", "close"]],
        df_right[["trade_date", "close"]],
        on="trade_date",
        how="inner",
        suffixes=("_left", "_right")
    )

    if df.empty:
        raise ValueError("aligned data is empty")

    # 5. 再次排序，避免 merge 后顺序异常
    df = df.sort_values("trade_date").reset_index(drop=True)

    # 6. 计算滚动收益率
    df["left_return"] = df["close_left"].pct_change(RETURN_WINDOW) * 100
    df["right_return"] = df["close_right"].pct_change(RETURN_WINDOW) * 100

    # 7. 计算收益价差
    df["spread"] = df["left_return"] - df["right_return"]

    # 8. 先删除滚动收益导致的空值
    df = df.dropna(subset=["left_return", "right_return", "spread"]).reset_index(drop=True)

    if df.empty:
        raise ValueError("not enough data after return window")

    # 9. 计算均线
    df["ma"] = df["spread"].rolling(MA_WINDOW).mean()

    # 10. 计算动态分位数，必须 expanding，不能全局回填
    df["p90_dynamic"] = df["spread"].expanding(min_periods=QUANTILE_WINDOW_MIN).quantile(0.9)
    df["p10_dynamic"] = df["spread"].expanding(min_periods=QUANTILE_WINDOW_MIN).quantile(0.1)

    # 11. 提前生成字符串日期，后面直接返回给前端
    df["date_str"] = df["trade_date"].dt.strftime("%Y-%m-%d")

    # 12. 先在完整有效区间上生成信号，不能先按 start_date 切片
    signals_all = []
    for i in range(1, len(df)):
        prev_spread = df["spread"].iloc[i - 1]
        curr_spread = df["spread"].iloc[i]
        prev_ma = df["ma"].iloc[i - 1]
        curr_ma = df["ma"].iloc[i]
        prev_p90 = df["p90_dynamic"].iloc[i - 1]
        prev_p10 = df["p10_dynamic"].iloc[i - 1]

        if pd.notna(prev_spread) and pd.notna(curr_spread) and pd.notna(prev_ma) and pd.notna(curr_ma):
            if pd.notna(prev_p90) and prev_spread > prev_ma and curr_spread < curr_ma and prev_spread > prev_p90:
                signals_all.append({
                    "date": df["date_str"].iloc[i],
                    "type": "sell",
                    "spread": round(float(curr_spread), 2)
                })
            elif pd.notna(prev_p10) and prev_spread < prev_ma and curr_spread > curr_ma and prev_spread < prev_p10:
                signals_all.append({
                    "date": df["date_str"].iloc[i],
                    "type": "buy",
                    "spread": round(float(curr_spread), 2)
                })

    # 13. 计算全局参考分位数
    global_p90 = float(df["spread"].quantile(0.9))
    global_p10 = float(df["spread"].quantile(0.1))

    # 14. 再按页面区间切片
    if start_date:
        df = df[df["date_str"] >= start_date].reset_index(drop=True)
        signals_all = [s for s in signals_all if s["date"] >= start_date]
    if end_date:
        df = df[df["date_str"] <= end_date].reset_index(drop=True)
        signals_all = [s for s in signals_all if s["date"] <= end_date]

    if df.empty:
        raise ValueError("empty after date filter")

    # 15. 归一化净值必须在切片后重算
    left_base = float(df["close_left"].iloc[0])
    right_base = float(df["close_right"].iloc[0])
    df["left_nav"] = df["close_left"] / left_base
    df["right_nav"] = df["close_right"] / right_base

    return {
        "dates": df["date_str"].tolist(),
        "left_close": df["close_left"].round(4).tolist(),
        "right_close": df["close_right"].round(4).tolist(),
        "left_return": df["left_return"].round(2).tolist(),
        "right_return": df["right_return"].round(2).tolist(),
        "spread": df["spread"].round(2).tolist(),
        "ma": df["ma"].round(2).tolist(),
        "p90_dynamic": df["p90_dynamic"].round(2).tolist(),
        "p10_dynamic": df["p10_dynamic"].round(2).tolist(),
        "left_nav": df["left_nav"].round(4).tolist(),
        "right_nav": df["right_nav"].round(4).tolist(),
        "signals": signals_all,
        "global_p90": round(global_p90, 2),
        "global_p10": round(global_p10, 2),
    }
```

### 不能改动的 pandas 细节

以下细节如果改了，结果就可能和参考实现不一致：

1. 必须用 `pd.merge(..., how="inner")` 对齐两个标的
2. 必须先 `sort_values("trade_date")` 再做 `pct_change`
3. 必须先算 `pct_change(250)`，再 `dropna`
4. `ma` 必须是 `spread.rolling(20).mean()`
5. 分位数必须是 `spread.expanding(min_periods=20).quantile(...)`
6. 信号必须先在完整有效区间生成，再按 `start_date/end_date` 过滤
7. `left_nav/right_nav` 必须在最终展示切片后重新归一化
8. 返回前所有列表都不能包含 `NaN`

### 和“看起来类似但其实不一样”的错误写法区分

下面这些写法都不算复刻：

1. 用 `outer join` 或 `left join` 对齐交易日
2. 用 `rolling(window).quantile()` 替代 `expanding().quantile()`
3. 先按页面时间范围筛数据，再算 `spread/ma/signals`
4. 用全样本一次性算 `p90/p10` 后回填到整条序列
5. 归一化净值用全历史第一天，而不是当前展示窗口第一天

### 固定默认参数

如果前端未传参数，后端默认值应为：

- `left_symbol = 399376`
- `right_symbol = 399373`
- `return_window = 250`
- `ma_window = 20`
- `quantile_window_min = 20`
- `start_date = null`
- `end_date = null`

这里的默认值只是默认展示组合。

实现时必须确保：

- 可以传入任意其他 `left_symbol/right_symbol`
- 换任意组合后，算法完全复用，不需要加特殊分支

### 数据不足时的处理规则

如果发生以下情况，接口应返回错误而不是返回空图：

1. 任一标的查不到数据
2. 两个标的按交易日对齐后数据为空
3. 有效数据长度不足 `return_window + 1`
4. 最终切片后无可展示数据

建议返回：

```json
{
  "code": 404,
  "message": "insufficient data",
  "data": null
}
```

### 第一步：准备计算区间

如果前端传入：

- `start_date = 2024-01-01`
- `end_date = 2026-03-20`

后端查询数据库时，不能只查这个区间。

因为需要：

- 250 个交易日滚动收益
- 20 日均线
- 动态分位数预热

所以建议实际查询起始时间：

- `calc_start_date = start_date - 400 个自然日`

`400` 不是数学必须值，但足够覆盖大多数 A 股 250 个交易日回看窗口。

### 第二步：读取两个标的收盘价

分别查询：

- `left_symbol`
- `right_symbol`

只取：

- `trade_date`
- `close`

并按 `trade_date` 升序排序。

### 第三步：按交易日对齐

对齐方式建议使用内连接：

- 只保留两个标的都存在数据的交易日

这样可以避免一个停牌、一个有数据时造成错位。

得到结构：

| trade_date | left_close | right_close |
|---|---:|---:|
| 2024-01-02 | 5234.12 | 6120.55 |
| 2024-01-03 | 5250.88 | 6112.01 |

### 第四步：计算滚动收益率

设滚动窗口为 `N = 250`。

公式：

```text
left_return_t = (left_close_t / left_close_{t-N} - 1) * 100
right_return_t = (right_close_t / right_close_{t-N} - 1) * 100
```

说明：

- 单位是百分比
- 前 250 个交易日无法计算，结果为空

### 第五步：计算收益价差

公式：

```text
spread_t = left_return_t - right_return_t
```

解释：

- `spread > 0`：左侧标的相对更强
- `spread < 0`：右侧标的相对更强

### 第六步：删除无效行

由于滚动收益前面会产生空值，所以需要删除：

- `left_return` 为空
- `right_return` 为空
- `spread` 为空

的数据行。

### 第七步：计算均线

设均线窗口为 `M = 20`。

公式：

```text
ma_t = mean(spread_{t-M+1} ... spread_t)
```

### 第八步：计算动态分位数

这里必须用扩充窗口，不能直接对全量样本一次性求分位数再回填，否则会有未来函数问题。

公式：

```text
p90_dynamic_t = quantile(spread_1 ... spread_t, 0.9)
p10_dynamic_t = quantile(spread_1 ... spread_t, 0.1)
```

最小样本建议：

- 至少 `20` 个有效点后再开始计算

也就是：

```text
expanding(min_periods=20)
```

### 第九步：生成买卖信号

买入信号定义：

```text
如果上一日 spread < 上一日 ma
并且当日 spread > 当日 ma
并且上一日 spread < 上一日 p10_dynamic
则当日产生 buy 信号
```

卖出信号定义：

```text
如果上一日 spread > 上一日 ma
并且当日 spread < 当日 ma
并且上一日 spread > 上一日 p90_dynamic
则当日产生 sell 信号
```

信号含义：

- `buy`：左侧风格从低位转强
- `sell`：左侧风格从高位转弱

建议按下面的伪代码实现：

```python
signals = []
for i in range(1, len(df)):
    prev_spread = df.iloc[i - 1]["spread"]
    curr_spread = df.iloc[i]["spread"]
    prev_ma = df.iloc[i - 1]["ma"]
    curr_ma = df.iloc[i]["ma"]
    prev_p90 = df.iloc[i - 1]["p90_dynamic"]
    prev_p10 = df.iloc[i - 1]["p10_dynamic"]

    if is_valid(prev_spread, curr_spread, prev_ma, curr_ma, prev_p90, prev_p10):
        if prev_spread > prev_ma and curr_spread < curr_ma and prev_spread > prev_p90:
            signals.append({
                "date": df.iloc[i]["trade_date"],
                "type": "sell",
                "spread": round(curr_spread, 2)
            })
        elif prev_spread < prev_ma and curr_spread > curr_ma and prev_spread < prev_p10:
            signals.append({
                "date": df.iloc[i]["trade_date"],
                "type": "buy",
                "spread": round(curr_spread, 2)
            })
```

### 第十步：按页面区间切片

信号应当先在全量计算区间里生成，然后再按页面展示区间过滤。

不能先切片再算信号，否则短区间会漏信号。

正确顺序：

1. 先用扩展区间做完整计算
2. 生成全量信号
3. 再按 `start_date/end_date` 裁切页面展示数据
4. 同步过滤落在展示区间内的信号

### 第十一步：重算归一化净值

页面展示时，净值曲线应该以当前展示窗口第一天为 1。

公式：

```text
left_nav_t = left_close_t / left_close_window_start
right_nav_t = right_close_t / right_close_window_start
```

这样用户切换时间区间时，净值图更直观。

### 第十二步：数值格式化

为了让前端简单，后端在返回前统一做格式化：

- `left_close`、`right_close`：保留 4 位小数
- `left_return`、`right_return`、`spread`、`ma`、`p90_dynamic`、`p10_dynamic`：保留 2 位小数
- `left_nav`、`right_nav`：保留 4 位小数
- `signals[].spread`：保留 2 位小数

如果某段序列前部因窗口不足出现空值，不要返回 `NaN`，统一处理为：

- 在进入最终返回前先删除无效计算区间
- 因此最终 `series` 数组中不应出现 `NaN`

## 必须遵守的返回契约

为了避免新 AI 自行发明字段，返回结构建议固定如下。

### 顶层结构

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "meta": {},
    "series": {},
    "summary": {},
    "signals": []
  }
}
```

### `meta` 字段

```json
{
  "left_symbol": "399376",
  "right_symbol": "399373",
  "left_name": "国证小盘成长",
  "right_name": "国证大盘价值",
  "return_window": 250,
  "ma_window": 20,
  "quantile_window_min": 20,
  "start_date": "2024-01-01",
  "end_date": "2026-03-20"
}
```

### `series` 字段

数组长度必须完全一致，并且按日期一一对应：

```json
{
  "dates": [],
  "left_close": [],
  "right_close": [],
  "left_return": [],
  "right_return": [],
  "spread": [],
  "ma": [],
  "p90_dynamic": [],
  "p10_dynamic": [],
  "left_nav": [],
  "right_nav": []
}
```

### `summary` 字段

建议固定为：

```json
{
  "latest_spread": 0,
  "latest_ma": 0,
  "latest_left_return": 0,
  "latest_right_return": 0,
  "global_p90": 0,
  "global_p10": 0,
  "signal_count": 0,
  "latest_signal": "none"
}
```

其中：

- `latest_spread`：最后一个交易日的 `spread`
- `latest_ma`：最后一个交易日的 `ma`
- `latest_left_return`：最后一个交易日的 `left_return`
- `latest_right_return`：最后一个交易日的 `right_return`
- `global_p90`：对完整有效计算区间的 `spread` 计算全局 90 分位数
- `global_p10`：对完整有效计算区间的 `spread` 计算全局 10 分位数
- `signal_count`：展示区间内信号条数
- `latest_signal`：展示区间最后一个交易日是否触发信号，没有则为 `none`

### `signals` 字段

```json
[
  {
    "date": "2024-08-20",
    "type": "buy",
    "spread": -2.44
  }
]
```

约束：

- `type` 只能是 `buy` 或 `sell`
- `date` 必须属于 `series.dates`
- `signals` 必须已经按展示区间过滤

## 建议给 AI 的实现验收条件

如果你想让新 AI 更稳定，可以要求它满足以下验收条件：

1. `GET /api/style-rotation` 在默认参数下可直接返回结果
2. 当数据库中只有一个标的数据时，接口返回 404
3. 当两个标的有效重叠数据少于 251 个交易日时，接口返回 404
4. `series` 内所有数组长度完全一致
5. 返回 JSON 中不允许出现 `NaN`
6. 信号必须先全量计算后切片，不能先切片再计算
7. 前端图上要能画出 `buy/sell` 点位
8. 页面修改日期区间后，`left_nav/right_nav` 必须以新窗口起点重新归一化到 1
9. 页面必须支持任意两个标的组合，不得写死为 `399376/399373`
10. 当切换到 `A:B`、`C:D`、`A:D` 这类不同组合时，后端和前端不需要改代码，只改参数即可

## 我对文档完整性的判断

如果只是“让 AI 生成一个可运行的第一版”，这份文档现在已经足够。

如果你的目标是“一次生成就尽量接近最终版”，关键依赖这几点：

1. 你在新会话里明确指定技术栈
2. 你要求它严格遵守本文档的接口和返回契约
3. 你要求它先实现后端计算，再接前端页面
4. 你要求它不要自行增加认证、权限、后台结构

在这几个前提下，新 AI 基本能准确落地。

## 前端页面需要展示的三组图

### 图 1：收益价差图

需要字段：

- `dates`
- `spread`
- `ma`
- `p90_dynamic` 或 `global_p90`
- `p10_dynamic` 或 `global_p10`
- `signals`

建议展示：

- `spread` 主线
- `ma` 虚线
- `buy/sell` 信号点
- 高低区域着色

### 图 2：左右标的滚动收益率对比

需要字段：

- `dates`
- `left_return`
- `right_return`

### 图 3：归一化净值对比

需要字段：

- `dates`
- `left_nav`
- `right_nav`

## 给 AI 写代码时的返回结构要求

为了让前端简单，返回结构建议固定成：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "meta": {},
    "series": {},
    "summary": {},
    "signals": []
  }
}
```

这样前端只需要：

1. 调一次接口
2. 直接拿 `data.series` 画图
3. 拿 `data.summary` 显示页头指标
4. 拿 `data.signals` 画买卖点

## 最小前端交互要求

单页即可，建议包含：

1. 两个标的选择框
2. 日期区间选择器
3. “同步数据”按钮
4. “开始分析”按钮
5. 三联图区域
6. 最新指标摘要卡片

## 最小后端技术要求

可以让 AI 按下面的最小栈写：

- Python 3.11+
- FastAPI
- SQLAlchemy 或 Tortoise ORM，任选其一
- SQLite
- pandas
- httpx 或 requests

如果从零重写，我更建议：

- FastAPI
- SQLAlchemy
- SQLite
- pandas

原因是：

- 社区资料更多
- AI 生成 SQLAlchemy 的成功率通常更高
- 后续迁移到 PostgreSQL 更顺

## 推荐给 AI 的一句话任务定义

你等下开新项目时，可以直接把下面这段扔给 AI：

```text
帮我从零创建一个风格轮动单页应用。后端用 FastAPI + SQLite + SQLAlchemy + pandas，前端用 Vue 3 + ECharts。不要登录，不要权限，不要后台管理。后端提供两个接口：POST /api/market-data/sync 用于拉取并入库两个指数或 ETF 的日线数据，GET /api/style-rotation 用于读取数据库数据并计算滚动收益、收益价差、20日均线、动态 p90/p10 分位数、买卖信号、归一化净值，并按固定 JSON 结构返回给前端单页展示。数据库至少包含 instruments 和 daily_prices 两张表，daily_prices 以 symbol + trade_date 唯一。计算逻辑严格按规格文档实现：先扩展查询窗口，再按日期对齐，再算 250 日滚动收益，再算 spread，再算 ma20，再用 expanding quantile 算动态 p90/p10，再生成 buy/sell 信号，最后按展示区间切片并重算净值。前端页面只要一个页面，包含标的选择、日期筛选、同步按钮、分析按钮和三联图。
```

如果你希望它更稳，建议把这段 prompt 改成下面这样：

```text
帮我从零创建一个风格轮动单页应用。后端用 FastAPI + SQLite + SQLAlchemy + pandas，前端用 Vue 3 + ECharts。不要登录，不要权限，不要后台管理。应用必须支持任意两个指数或 ETF 做对比，不能把逻辑写死成固定两只。后端至少提供三个接口：GET /api/instruments 返回可选标的列表，POST /api/market-data/sync 用于拉取并入库指定标的日线数据，GET /api/style-rotation 用于读取任意 left_symbol/right_symbol 的历史数据并计算滚动收益、收益价差、20日均线、动态 p90/p10 分位数、买卖信号、归一化净值，并按规格文档中的固定 JSON 结构返回。数据库至少包含 instruments 和 daily_prices 两张表，daily_prices 以 symbol + trade_date 唯一。计算逻辑必须严格遵守规格文档和黄金测试样例，不允许自行更改返回字段、公式、DataFrame 处理顺序或信号判定顺序。先完成后端并通过黄金测试样例，再实现前端单页。
```

## 结论

这个新项目的本质不是“迁移老系统”，而是“重写一个非常轻的策略可视化工具”。

最小闭环只有四件事：

1. 拉数据
2. 存数据
3. 算指标
4. 单页展示

剩下的系统能力都不要带进去。
