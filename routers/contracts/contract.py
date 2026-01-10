# routers/contracts.py
import ccxt.async_support as ccxt_async  # 使用异步版支持WebSocket高效推送
import ccxt  # 同步版，直接受益于你的全局apply_global_ccxt_patch()
import ccxt.pro as ccxt_pro 
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi import Query, HTTPException
from typing import List, Dict, Optional
import asyncio
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# 预定义常用实例（缓存复用）
SYNC_INSTANCE_CACHE: Dict[str, ccxt.Exchange] = {}

def get_sync_exchange_instance(
    exchange_name: str = "okx",
    contract_type: str = "linear"
) -> ccxt.Exchange:
    """
    支持客户端任意传入交易所名称（小写），自动创建ccxt实例
    客户端示例：?exchange=bybit&type=linear
              ?exchange=gate&type=linear
              ?exchange=mexc&type=linear
    """
    key = f"{exchange_name}_{contract_type}"
    if key in SYNC_INSTANCE_CACHE:
        return SYNC_INSTANCE_CACHE[key]

    config = {}  # 依赖全局补丁注入代理/timeout/rateLimit

    # 特殊处理需要自定义urls或options的交易所
    if exchange_name == "binance":
        config["urls"] = {
            "api": {
                "fapi": "https://fapi.binance.com/fapi/v1",
                "public": "https://fapi.binance.com/fapi/v1",
                "private": "https://fapi.binance.com/fapi/v1",
            }
        }
        config["options"] = {"defaultType": "future" if contract_type == "linear" else "delivery"}

    elif exchange_name in ["bybit", "bitget"]:  # 注意拼写：bigget → bitget
        config["options"] = {"defaultType": "swap"}

    elif exchange_name in ["okx", "gate", "mexc", "kucoin", "huobi", "htx"]:
        # 大多数亚洲CEX默认就是swap/linear，无需额外配置
        config["options"] = {"defaultType": "swap"}

    else:
        # 其他交易所直接用默认配置（ccxt会自动处理）
        pass

    # 动态创建实例（ccxt支持字符串作为类名）
    try:
        exchange_class = getattr(ccxt, exchange_name)
        ex = exchange_class(config)
    except AttributeError:
        raise ValueError(f"CCXT不支持的交易所名称: {exchange_name}（请检查拼写，小写）")

    SYNC_INSTANCE_CACHE[key] = ex
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
    ex = get_sync_exchange_instance(exchange, type)
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
    

# ==========================================
# ==========================================

# 热门U本位永续合约（不同交易所symbol格式不同）
EXCHANGE_SYMBOLS = {
    # "bybit": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"],
    # "okx": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT"],
    "bingx": ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"],
    "bitget": ["0G/USDT:USDT"],
}

# 创建实例的工厂函数
def create_pro_exchange(name: str) -> ccxt_pro.Exchange:
    if name == "bybit":
        return ccxt_pro.bybit({"options": {"defaultType": "swap"}})
    elif name == "okx":
        return ccxt_pro.okx()
    elif name == "bingx":
        return ccxt_pro.bingx({"options": {"defaultType": "swap"}})
    elif name == "bitget":
        return ccxt_pro.bitget({"options": {"defaultType": "swap"}})
    else:
        raise ValueError(f"不支持的交易所: {name}")

@router.websocket("/ws/contracts")
async def ws_multi_contracts(
    websocket: WebSocket,
    exchange: str = Query("bybit", description="bybit | okx | bingx | bitget | all")
):
    await websocket.accept()
    logger.info(f"多交易所WS连接成功，指定: {exchange}")

    # 支持all = 所有交易所
    if exchange == "all":
        target_exchanges = list(EXCHANGE_SYMBOLS.keys())
    elif exchange in EXCHANGE_SYMBOLS:
        target_exchanges = [exchange]
    else:
        await websocket.send_json({"error": "不支持的交易所"})
        await websocket.close(code=1000)
        return

    pro_instances: Dict[str, ccxt_pro.Exchange] = {}
    tasks = []

    try:
        # 为每个交易所创建独立实例
        for ex_name in target_exchanges:
            ex = create_pro_exchange(ex_name)
            pro_instances[ex_name] = ex

            # 尝试加载市场（失败用保底symbol）
            loaded = False
            try:
                if ex_name == "bybit":
                    await ex.load_markets(params={"category": "linear"})
                elif ex_name == "okx":
                    await ex.load_markets(params={"instType": "SWAP"})
                elif ex_name == "bingx":
                    await ex.load_markets(params={"category": "perpetual"})
                elif ex_name == "bitget":
                    await ex.load_markets()
                loaded = True
                logger.info(f"{ex_name} markets加载成功")
            except Exception as e:
                logger.warning(f"{ex_name} markets加载失败: {e}")

            symbols = EXCHANGE_SYMBOLS[ex_name][:5]  # 每家取5个
            logger.info(f"{ex_name} 开始推送 {len(symbols)} 个合约: {symbols}")

            for symbol in symbols:
                tasks.append(asyncio.create_task(ticker_task(ex, symbol, websocket, ex_name)))

        await asyncio.gather(*tasks, return_exceptions=True)

    except WebSocketDisconnect:
        logger.info("WS客户端正常断开")
    except Exception as e:
        logger.error(f"WS异常: {e}")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.sleep(0.1)  # 给任务100ms时间响应取消
        for ex in pro_instances.values():
            await ex.close()

# 通用ticker任务（手动提取字段，避免解析bug）
async def ticker_task(ex: ccxt_pro.Exchange, symbol: str, ws: WebSocket, ex_name: str):
    while True:
        try:
            ticker = await ex.watch_ticker(symbol)
            data = {
                "type": "ticker",
                "exchange": ex_name,
                "symbol": symbol,
                "last": ticker.get("last") or ticker.get("lastPrice") or ticker.get("lastPx"),
                "change": ticker.get("percentage") or ticker.get("price24hPcnt") or ticker.get("priceChangePercent"),
                "volume_24h": ticker.get("baseVolume") or ticker.get("volume24h"),
                "timestamp": ticker.get("timestamp") or ticker.get("ts"),
            }
            await ws.send_json(data)
        except Exception as e:
            logger.warning(f"{ex_name} {symbol} ticker错误: {type(e).__name__}: {e}")
            await asyncio.sleep(5)