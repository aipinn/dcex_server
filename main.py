from utils.ccxt_patch import apply_global_ccxt_patch
from fastapi import WebSocket, Query

# 导入 FastAPI 主类和 Query（用于定义查询参数）。
# 导入 ccxt 库（核心工具）。
from fastapi import FastAPI
from routers import ticker  # 导入路由模块
from routers import pairs
from routers import exchange
from routers import summary
from routers import ohlc
from routers import order_book
from routers import trades
from routers import ws_ticker
from routers import ws_orderbook

from utils.logger import setup_logging
from routers.contracts import contract

setup_logging()

# -----------------------------------------------------------------------
# 1. 应用 CCXT 全局补丁
#   全局应用 CCXT 代理和限速补丁
#   需要代码源文件中开启VPN代理
#       1. Clash全局不行，也不合适
#       2. 在终端中配置proxy也不行，虽然配置后curl可以正常访问，但是python脚本中ccxt请求依然不走代理
#       3. 所以只能在代码中强制指定代理
apply_global_ccxt_patch()

# -----------------------------------------------------------------------
# 2. 创建App实例
#   创建 FastAPI 应用实例。
#   设置了 API 的标题、描述、版本，启动后访问 /docs 会看到美观的 Swagger 交互文档
app = FastAPI(
    title="CCXT Proxy API", description="简单代理多个交易所的价格获取", version="1.0"
)

# -----------------------------------------------------------------------
# 3. 注册路由（前缀可选）
app.include_router(ticker.router, prefix="/api")  # 可选加前缀 /api/ticker

app.include_router(pairs.router, prefix="/api")

app.include_router(exchange.router, prefix="/api")

app.include_router(summary.router, prefix="/api")

app.include_router(ohlc.router, prefix="/api")

app.include_router(order_book.router, prefix="/api")

app.include_router(trades.router, prefix="/api")

# 注册合约路由
app.include_router(contract.router, prefix="/api") 

# app.include_router(ws_ticker.router, prefix="")


# WS 接口直接在 app 上注册（路径随意）
@app.websocket("/api/ws/ticker")
async def ticker_ws(websocket: WebSocket, exchange: str = Query("binance")):
    await ws_ticker.websocket_ticker(websocket, exchange)  # 调用分离的逻辑

@app.websocket("/api/ws/orderbook")
async def orderbook_ws(
    websocket: WebSocket,
    exchange: str = Query("binance"),
):
    await ws_orderbook.websocket_orderbook(websocket, exchange)