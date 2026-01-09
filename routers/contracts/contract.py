# # routers/contracts.py
# import ccxt.async_support as ccxt_async  # 使用异步版支持WebSocket高效推送
# from fastapi import APIRouter, WebSocket, WebSocketDisconnect
# from typing import List, Dict, Optional
# import asyncio
# import logging

# router = APIRouter()

# # -----------------------------------------------------------------------
# # 交易所实例配置（仅在此文件内创建，避免全局同步阻塞）
# # 支持 Binance U本位、Binance 币本位、OKX、Bybit（后续可扩展）
# # -----------------------------------------------------------------------
# EXCHANGES: Dict[str, ccxt_async.Exchange] = {
#     "binance_linear": ccxt_async.binance({                     # Binance U本位永续合约（Linear / USDT-Margined）
#         "options": {"defaultType": "future"},
#     }),
#     "binance_inverse": ccxt_async.binance({                    # Binance 币本位合约（Inverse / Coin-Margined）
#         "options": {"defaultType": "delivery"},
#     }),
#     "okx": ccxt_async.okx(),                                  # OKX 一个实例，symbol区分U本位/币本位
#     "bybit": ccxt_async.bybit({                                # Bybit Unified Account，支持两者
#         "options": {"defaultType": "swap"},
#     }),
# }

# # 缓存已加载的市场信息，避免每次请求都重新load_markets
# MARKETS_CACHE: Dict[str, List[Dict]] = {}

# logger = logging.getLogger(__name__)

# # -----------------------------------------------------------------------
# # 辅助函数：加载并缓存所有合约市场
# # -----------------------------------------------------------------------
# async def load_all_contract_markets() -> Dict[str, List[Dict]]:
#     """加载所有交易所的永续合约市场信息，并按交易所缓存"""
#     if MARKETS_CACHE:
#         return MARKETS_CACHE

#     for name, exchange in EXCHANGES.items():
#         await exchange.load_markets()
#         # 只保留永续合约（swap），排除交割合约
#         contracts = [
#             market for market in exchange.markets.values()
#             if market.get("swap") and market.get("contract")
#         ]
#         MARKETS_CACHE[name] = [
#             {
#                 "symbol": m["symbol"],                    # 统一符号，如 BTC/USDT:USDT
#                 "base": m["base"],                        # 基础币
#                 "quote": m["quote"],                      # 计价币
#                 "linear": m.get("linear", False),         # True = U本位
#                 "inverse": m.get("inverse", False),       # True = 币本位
#                 "max_leverage": m["limits"]["leverage"].get("max", None),
#                 "exchange": name.split("_")[0],           # 显示用交易所名，如 binance
#                 "exchange_key": name,                      # 内部区分linear/inverse实例
#             }
#             for m in contracts
#         ]
#     return MARKETS_CACHE

# # -----------------------------------------------------------------------
# # REST 接口：获取合约交易对列表
# #   ?type=linear | inverse | all   （默认all）
# # -----------------------------------------------------------------------
# @router.get("/contracts/markets")
# async def get_contracts_markets(type: Optional[str] = "all"):
#     """
#     返回聚合的多交易所永续合约列表
#     - type=linear  只返回U本位合约
#     - type=inverse 只返回币本位合约
#     - type=all     返回全部（默认）
#     """
#     all_markets = await load_all_contract_markets()
#     result: List[Dict] = []

#     for markets in all_markets.values():
#         for m in markets:
#             if type == "linear" and not m["linear"]:
#                 continue
#             if type == "inverse" and not m["inverse"]:
#                 continue
#             result.append(m)

#     # 按 symbol 排序，便于前端展示
#     result.sort(key=lambda x: x["symbol"])
#     return result

# # -----------------------------------------------------------------------
# # WebSocket 接口：实时推送 ticker + funding rate
# #   客户端连接后会持续接收热门合约的更新
# # -----------------------------------------------------------------------
# @router.websocket("/ws/contracts")
# async def websocket_contracts(websocket: WebSocket):
#     await websocket.accept()
#     tasks = []
#     try:
#         # 为每个交易所的前20个热门合约开启监听任务（可后续改为客户端订阅指定symbol）
#         for ex_name, exchange in EXCHANGES.items():
#             markets = MARKETS_CACHE.get(ex_name, [])
#             # 简单取前20个（实际可按交易量排序）
#             symbols = [m["symbol"] for m in markets[:20]]

#             for symbol in symbols:
#                 task = asyncio.create_task(_watch_symbol(exchange, symbol, websocket))
#                 tasks.append(task)

#         await asyncio.gather(*tasks)
#     except WebSocketDisconnect:
#         logger.info("合约WebSocket客户端断开连接")
#     except Exception as e:
#         logger.error(f"合约WebSocket错误: {e}")
#     finally:
#         for task in tasks:
#             task.cancel()

# async def _watch_symbol(exchange: ccxt_async.Exchange, symbol: str, ws: WebSocket):
#     """单个symbol的监听循环，推送ticker和funding rate"""
#     while True:
#         try:
#             # 并行获取ticker和funding rate（如果支持）
#             ticker_task = exchange.watch_ticker(symbol)
#             funding_task = None
#             if hasattr(exchange, "watch_funding_rate"):
#                 funding_task = exchange.watch_funding_rate(symbol)

#             ticker, funding = await asyncio.gather(ticker_task, funding_task or asyncio.sleep(0))

#             data = {
#                 "exchange": exchange.id,
#                 "symbol": symbol,
#                 "ticker": ticker,
#                 "funding_rate": funding["fundingRate"] if funding else None,
#                 "next_funding_time": funding["fundingDatetime"] if funding else None,
#             }
#             await ws.send_json(data)
#         except Exception as e:
#             # 网络波动或symbol下线时暂停后重试
#             logger.warning(f"{exchange.id} {symbol} WS错误: {e}")
#             await asyncio.sleep(5)

# routers/contracts.py
import ccxt  # 同步版，直接受益于你的全局apply_global_ccxt_patch()
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Optional
import logging
from fastapi import Query

router = APIRouter()
logger = logging.getLogger(__name__)
# routers/contracts.py（新增动态参数支持）


# 预定义常用实例（缓存复用）
INSTANCE_CACHE: Dict[str, ccxt.Exchange] = {}

def get_exchange_instance(exchange_name: str = "binance", contract_type: str = "linear"):
    """
    根据客户端传参动态返回CCXT实例
    - exchange_name: binance | okx | bybit
    - contract_type: linear (U本位) | inverse (币本位)
    """
    key = f"{exchange_name}_{contract_type}"
    if key in INSTANCE_CACHE:
        return INSTANCE_CACHE[key]

    config = {
        # proxies 已由全局补丁注入，无需重复
    }

    if exchange_name == "binance":
        config["urls"] = {
            "api": {
                "fapi": "https://fapi.binance.com/fapi/v1",  # 强制U本位合约端点
                "public": "https://fapi.binance.com/fapi/v1",
                "private": "https://fapi.binance.com/fapi/v1",
            }
        }
        if contract_type == "linear":
            config["options"] = {"defaultType": "future"}  # U本位永续
        elif contract_type == "inverse":
            config["options"] = {"defaultType": "delivery"}  # 币本位
        ex = ccxt.binance(config)
    elif exchange_name == "okx":
        ex = ccxt.okx(config)  # OKX 一个实例，symbol区分
    elif exchange_name == "bybit":
        config["options"] = {"defaultType": "swap"}
        ex = ccxt.bybit(config)
    else:
        raise ValueError("不支持的交易所")

    INSTANCE_CACHE[key] = ex
    return ex

@router.get("/contracts/markets")
def get_contracts_markets(
    exchange: str = Query("binance", description="交易所: binance | okx | bybit"),
    type: str = Query("linear", description="合约类型: linear (U本位) | inverse (币本位)")
):
    """
    客户端可传参数控制返回哪家交易所的哪类合约
    示例：
    /api/contracts/markets?exchange=binance&type=linear   → Binance U本位
    /api/contracts/markets?exchange=binance&type=inverse  → Binance 币本位
    /api/contracts/markets?exchange=okx&type=linear       → OKX U本位（OKX无币本位区分）
    """
    ex = get_exchange_instance(exchange, type)
    try:
        ex.load_markets()
        contracts = [m for m in ex.markets.values() if m.get("swap") and m.get("contract")]
        result = [
            {
                "symbol": m["symbol"],
                "base": m["base"],
                "quote": m["quote"],
                "linear": m.get("linear", False),
                "inverse": m.get("inverse", False),
                "max_leverage": m.get("limits", {}).get("leverage", {}).get("max"),
                "exchange": exchange,
            }
            for m in contracts
        ]
        if type == "linear":
            result = [r for r in result if r["linear"]]
        elif type == "inverse":
            result = [r for r in result if r["inverse"]]

        result.sort(key=lambda x: x["symbol"])
        return result
    except Exception as e:
        logger.error(f"加载 {exchange} {type} 合约失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))