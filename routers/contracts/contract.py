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
# routers/contracts.py（完全动态版，支持 109 个 ccxt.pro 交易所）

# 保底主流 U 本位永续合约（客户端不传 symbols 时使用）
DEFAULT_SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT"
]

# 少数需要特殊 load_markets 参数的交易所（其他默认就行）
SPECIAL_LOAD_PARAMS = {
    "bybit": {"category": "linear"},
    "okx": {"instType": "SWAP"},
    "bingx": {"category": "perpetual"},
    "bitget": {},
    "gate": {"type": "swap"},
    "mexc": {"type": "swap"},
}

@router.websocket("/ws/contracts")
async def ws_dynamic_contracts(
    websocket: WebSocket,
    exchange: str = Query(..., description="任意 ccxt.pro 支持的小写交易所名，如 bybit、okx、gate、mexc..."),
    symbols: str = Query(None, description="可选，逗号分隔的 symbol 列表，如 BTCUSDT,ETHUSDT（不传用保底）")
):
    await websocket.accept()
    alive = asyncio.Event()
    alive.set()
    logger.info(f"WS 连接成功，交易所: {exchange}")

    # 动态创建 ccxt.pro 实例（支持全部 109 个）
    try:
        config = {
            "options": {"defaultType": "swap"},  # 默认 U 本位永续
            "enableRateLimit": True,
        }
        exchange_class = getattr(ccxt_pro, exchange)
        ex = exchange_class(config)
    except AttributeError:
        await websocket.send_json({"error": f"ccxt.pro 不支持该交易所: {exchange}（请检查拼写，小写）"})
        await websocket.close(code=1000)
        return
    except Exception as e:
        await websocket.send_json({"error": f"创建实例失败: {str(e)}"})
        await websocket.close(code=1000)
        return

    tasks = []
    try:
        # 尝试加载市场（特殊交易所用 params）
        try:
            params = SPECIAL_LOAD_PARAMS.get(exchange, {})
            await ex.load_markets(params=params)
            logger.info(f"{exchange} markets 加载成功")
        except Exception as e:
            logger.warning(f"{exchange} markets 加载失败: {e}")

        # symbol 来源：客户端传 > 保底
        if symbols:
            target_symbols = [s.strip() for s in symbols.split(",")][:10]  # 最多 10 个，防滥用
        else:
            target_symbols = DEFAULT_SYMBOLS[:5]

        logger.info(f"{exchange} 开始推送 {len(target_symbols)} 个合约: {target_symbols}")

        for symbol in target_symbols:
            tasks.append(asyncio.create_task(ticker_task(ex, symbol, websocket, exchange, alive)))

        await asyncio.gather(*tasks, return_exceptions=True)

    except WebSocketDisconnect:
        logger.info("WS 客户端正常断开")
    except Exception as e:
        logger.error(f"WS 异常: {e}")
    finally:
        alive.clear()
        await asyncio.sleep(0.1)  # 给任务响应取消
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ex.close()
        logger.info("WS 资源已清理")

# ticker 任务（手动提取字段 + 关闭检测 + 无效价格过滤）
async def ticker_task(
    ex: ccxt_pro.Exchange,
    symbol: str,
    ws: WebSocket,
    ex_name: str,
    alive: asyncio.Event,
):
    while alive.is_set():
        try:
            ticker = await ex.watch_ticker(symbol)

            # 检测 WS 是否已关闭
            if not alive.is_set() or ws.client_state.name != "CONNECTED":
                logger.debug(f"{ex_name} {symbol} WS 已关闭，停止 ticker 任务")
                break

            data = {
                "type": "ticker",
                "exchange": ex_name,
                "symbol": symbol,
                "last": ticker.get("last") or ticker.get("lastPrice") or ticker.get("lastPx"),
                "change": ticker.get("percentage") or ticker.get("price24hPcnt") or ticker.get("priceChangePercent"),
                "volume_24h": ticker.get("baseVolume") or ticker.get("volume24h"),
                "timestamp": ticker.get("timestamp") or ticker.get("ts"),
            }

            # 过滤无效价格，不发垃圾数据
            if data["last"] is None or data["last"] <= 0:
                logger.warning(f"{ex_name} {symbol} 无效价格，跳过发送")
                await asyncio.sleep(5)
                continue

            await ws.send_json(data)

        except ccxt.BadSymbol as e:
            # ❌ 不支持的 symbol —— 不可恢复
            logger.warning(f"{ex_name} {symbol} 不存在: {e}")

            # 通知 client（只发一次）
            if ws.client_state.name == "CONNECTED":
                await ws.send_json({
                    "type": "error",
                    "exchange": ex_name,
                    "symbol": symbol,
                    "reason": "symbol_not_supported",
                })

            break  # ⭐ 关键：直接结束这个 symbol 的 task

        except WebSocketDisconnect:
            # 客户端主动断开
            logger.info(f"{ex_name} {symbol} WS 客户端断开")
            break

        except RuntimeError as e:
            # WS 已 close 再 send 会进这里
            logger.info(f"{ex_name} {symbol} WS 已关闭: {e}")
            break

        except Exception as e:
            # ✅ 网络抖动、临时错误，允许 retry
            logger.warning(f"{ex_name} {symbol} ticker 临时异常: {type(e).__name__}: {e}")
            await asyncio.sleep(5)