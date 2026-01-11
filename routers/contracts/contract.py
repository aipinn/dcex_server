# routers/contracts.py
import ccxt  # 同步版，直接受益于你的全局apply_global_ccxt_patch()
import ccxt.pro as ccxt_pro
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from typing import Dict, List, Optional
import asyncio
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# 预定义常用实例（缓存复用）
SYNC_INSTANCE_CACHE: Dict[str, ccxt.Exchange] = {}

def get_sync_exchange_instance(
    exchange_name: str = "okx",
    contract_type: str = "linear"  # 新增支持：linear (U本位) | inverse (币本位)
) -> ccxt.Exchange:
    """
    支持客户端任意传入交易所名称（小写），自动创建ccxt实例
    客户端示例：?exchange=bybit&type=linear
              ?exchange=gate&type=inverse
    """
    key = f"{exchange_name}_{contract_type}"
    if key in SYNC_INSTANCE_CACHE:
        return SYNC_INSTANCE_CACHE[key]

    config = {}  # 故意为空，依赖全局补丁注入代理/timeout/limit

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

    elif exchange_name in ["bybit", "bitget"]:
        config["options"] = {"defaultType": "swap" if contract_type == "linear" else "inverse"}

    elif exchange_name in ["okx", "gate", "mexc", "kucoin", "huobi", "htx"]:
        # 大多数亚洲CEX默认就是swap/linear/inverse，无需额外配置
        config["options"] = {"defaultType": "swap" if contract_type == "linear" else "inverse"}

    else:
        # 其他交易所直接用默认配置（ccxt会自动处理）
        config["options"] = {"defaultType": "swap" if contract_type == "linear" else "inverse"}

    # 动态创建实例（ccxt支持字符串作为类名）
    try:
        exchange_class = getattr(ccxt, exchange_name)
        ex = exchange_class(config)
    except AttributeError:
        raise ValueError(f"CCXT不支持的交易所名称: {exchange_name}（请检查拼写，小写）")

    SYNC_INSTANCE_CACHE[key] = ex
    return ex


# 某些交易所 load_markets 需要额外参数，否则 WS 会歧义 / 报错
SPECIAL_LOAD_PARAMS = {
    # OKX：必须指定 marketType，否则 BTC-USDT-SWAP 会歧义
    "okx": {
        "type": "swap",
    },

    # 如果以后发现其他交易所有类似问题，再加
    # "bybit": {...},
    # "gate": {...},
}

@router.get("/contracts/markets")
def get_contracts_markets(
    exchange: str = Query("binance", description="交易所: binance | okx | bybit | gate | mexc..."),
    type: str = Query("linear", description="linear (U本位) | inverse (币本位)")
):
    """
    客户端可传参数控制返回哪家交易所的哪类合约
    示例：
    /api/contracts/markets?exchange=binance&type=linear → Binance U本位
    /api/contracts/markets?exchange=binance&type=inverse → Binance 币本位
    /api/contracts/markets?exchange=okx&type=linear → OKX U本位
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
        # 客户端指定类型过滤（保持你原有逻辑）
        if type == "linear":
            result = [r for r in result if r["linear"]]
        elif type == "inverse":
            result = [r for r in result if r["inverse"]]

        result.sort(key=lambda x: x["symbol"])
        logger.info(f"返回 {exchange} {type} 合约 {len(result)} 个")
        return {"data": result}
    except Exception as e:
        logger.error(f"加载 {exchange} {type} 合约失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# WS 部分：支持客户端传 type 区分 U本位 / 币本位
# ==========================================

# 保底主流合约（区分 U本位 / 币本位）
DEFAULT_SYMBOLS_LINEAR = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT"
]

DEFAULT_SYMBOLS_INVERSE = [
    "BTC/USD:BTC", "ETH/USD:BTC", "SOL/USD:BTC", "XRP/USD:BTC", "DOGE/USD:BTC"
]  # Binance/Bybit常见inverse格式，客户端可覆盖

@router.websocket("/ws/contracts")
async def ws_dynamic_contracts(
    websocket: WebSocket,
    exchange: str = Query(..., description="任意ccxt.pro支持的小写交易所名，如 bybit、okx、gate、mexc..."),
    type: str = Query("linear", description="linear (U本位) | inverse (币本位)"),
    symbols: str = Query(None, description="可选，逗号分隔的symbol列表，如 BTCUSDT,ETHUSDT（不传用保底）")
):
    await websocket.accept()
    alive = asyncio.Event()
    alive.set()
    logger.info(f"WS连接成功，交易所: {exchange}，类型: {type}")

    # 动态创建实例
    try:
        config = {
            "options": {"defaultType": "swap" if type == "linear" else "inverse"},
            "enableRateLimit": True,
        }
        exchange_class = getattr(ccxt_pro, exchange)
        ex = exchange_class(config)
    except AttributeError:
        await websocket.send_json({"error": f"ccxt.pro不支持该交易所: {exchange}"})
        await websocket.close(code=1000)
        return
    except Exception as e:
        await websocket.send_json({"error": f"创建实例失败: {str(e)}"})
        await websocket.close(code=1000)
        return

    tasks = []
    try:
        # 尝试加载市场
        try:
            params = SPECIAL_LOAD_PARAMS.get(exchange, {})
            await ex.load_markets(params=params)
            logger.info(f"{exchange} markets加载成功")
        except Exception as e:
            logger.warning(f"{exchange} markets加载失败: {e}")

        # symbol来源：客户端传 > 保底（区分类型）
        if symbols:
            target_symbols = [s.strip() for s in symbols.split(",")][:10]  # 最多 10 个，防滥用
        else:
            target_symbols = DEFAULT_SYMBOLS_LINEAR if type == "linear" else DEFAULT_SYMBOLS_INVERSE

        logger.info(f"{exchange} {type} 开始推送 {len(target_symbols)} 个合约: {target_symbols}")

        for symbol in target_symbols:
            tasks.append(asyncio.create_task(ticker_task(ex, symbol, websocket, exchange, alive)))

        await asyncio.gather(*tasks, return_exceptions=True)

    except WebSocketDisconnect:
        logger.info("WS客户端正常断开")
    except Exception as e:
        logger.error(f"WS异常: {e}")
    finally:
        alive.clear()
        await asyncio.sleep(0.1)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ex.close()
        logger.info("WS资源已清理")

# ticker任务（保持你原有异常处理风格，只加关闭检测）
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

            if not alive.is_set() or ws.client_state.name != "CONNECTED":
                logger.debug(f"{ex_name} {symbol} WS已关闭，停止任务")
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

            if data["last"] is None or data["last"] <= 0:
                logger.warning(f"{ex_name} {symbol} 无效价格，跳过")
                await asyncio.sleep(5)
                continue

            await ws.send_json(data)

        except ccxt.BadSymbol as e:
            # ❌ 不支持的 symbol —— 不可恢复
            logger.warning(f"{ex_name} {symbol} 不存在: {e}")
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