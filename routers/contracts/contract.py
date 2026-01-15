# routers/contracts.py
import ccxt  # 同步版，直接受益于你的全局apply_global_ccxt_patch()
import ccxt.pro as ccxt_pro
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from typing import Dict, List, Optional
import asyncio
import logging
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)

# 预定义常用实例（缓存复用）
SYNC_INSTANCE_CACHE: Dict[str, ccxt.Exchange] = {}


def get_sync_exchange_instance(
    exchange_name: str = "okx",
    contract_type: str = "linear"  # linear (U本位) | inverse (币本位)
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
        config["options"] = {"defaultType": "swap" if contract_type == "linear" else "inverse"}
    else:
        config["options"] = {"defaultType": "swap" if contract_type == "linear" else "inverse"}

    # 动态创建实例
    try:
        exchange_class = getattr(ccxt, exchange_name)
        ex = exchange_class(config)
    except AttributeError:
        raise ValueError(f"CCXT不支持的交易所名称: {exchange_name}（请检查拼写，小写）")

    SYNC_INSTANCE_CACHE[key] = ex
    return ex

# 某些交易所 load_markets 需要额外参数，否则 WS 会歧义 / 报错
SPECIAL_LOAD_PARAMS = {
    "okx": {"type": "swap"},
    # 如果以后发现其他交易所有类似问题，再加
}

@router.get("/contracts/markets")
def get_contracts_markets(
    exchange: str = Query("okx"),
    type: str = Query("linear"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=10, le=100),
    sort: str = Query("symbol"),
    order: str = Query("asc")
):
    try:
        ex = get_sync_exchange_instance(exchange, type)

        ex.load_markets(params=SPECIAL_LOAD_PARAMS.get(exchange, {}))

        # 1. 构建完整交易对列表
        contracts = [m for m in ex.markets.values() if m.get("swap") and m.get("contract")]

        result = [
            {
                "symbol": m["symbol"],
                "base": m["base"],
                "quote": m["quote"],
                "linear": m.get("linear", False),
                "inverse": m.get("inverse", False),
                "maxLeverage": m.get("limits", {}).get("leverage", {}).get("max"),
                "minLeverage": m.get("limits", {}).get("leverage", {}).get("min"),
                "exchange": exchange,
                # 预留资金费率字段
                "fundingRate": -0,
                "nextFundingTime": -0,
            }
            for m in contracts
        ]

        logger.info('🍌 market info: %s', contracts[0] if contracts else "无合约")

        # 类型过滤 + 排序 + 分页（原有逻辑）
        if type == "linear":
            result = [r for r in result if r["linear"]]
        elif type == "inverse":
            result = [r for r in result if r["inverse"]]

        # 排序字段校验
        allowed_sort = ["symbol", "volume_24h", "priceChange", "leverage", "fundingRate"]
        sort = sort if sort in allowed_sort else "symbol"
        reverse = order.lower() == "desc"
        result.sort(key=lambda x: x.get(sort, 0) if sort != "symbol" else x["symbol"], reverse=reverse)

        start = (page - 1) * limit
        paginated = result[start:start + limit]

        # 2. 批量拉取资金费率（只对当前页的 symbol 拉取，节省请求）
        symbols = [r["symbol"] for r in paginated]
        if symbols:
            try:
                funding_data = ex.fetch_funding_rates(symbols)  # 批量获取
                for r in paginated:
                    funding = funding_data.get(r["symbol"], {})
                    r["fundingRate"] = funding.get("fundingRate", -0)
                    r["nextFundingTime"] = funding.get("nextFundingTime", -0) or funding.get("fundingTimestamp", -0)
                logger.info(f"成功拉取 {len(symbols)} 个合约的资金费率")
            except Exception as e:
                logger.warning(f"拉取资金费率失败: {e}，字段保持默认值")

        # 统一返回结构
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "result": paginated,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": len(result),
                    "total_pages": (len(result) + limit - 1) // limit,
                    "sort": sort,
                    "order": order
                }
            },
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except ValueError as e:
        logger.error(f"Contracts REST ValueError: {str(e)}")
        return {
            "code": 4001,
            "msg": str(e),
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except Exception as e:
        logger.error(f"Contracts REST 异常: {str(e)}")
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
]


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
        }
        exchange_class = getattr(ccxt_pro, exchange)
        ex = exchange_class(config)
    except AttributeError:
        await websocket.send_json({
            "code": 4001,
            "msg": f"ccxt.pro不支持该交易所: {exchange}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        })
        await websocket.close(code=1000)
        return
    except Exception as e:
        await websocket.send_json({
            "code": 5000,
            "msg": f"创建实例失败: {str(e)}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        })
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
        try:
            await websocket.send_json({
                "code": 5000,
                "msg": f"WS异常: {str(e)}",
                "data": None,
                "ts": int(datetime.utcnow().timestamp() * 1000)
            })
        except:
            pass
    finally:
        alive.clear()
        await asyncio.sleep(0.1)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ex.close()
        logger.info("WS资源已清理")


# ticker任务（保持原有异常处理风格，只加关闭检测 + 统一响应格式）
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
            logger.info('🌹 ticker info: %s', ticker)

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
                "fundingRate": ticker.get("fundingRate") or ticker.get("funding_rate")
                               or ticker.get("info", {}).get("fundingRate") or -0,
                "nextFundingTime": ticker.get("nextFundingTime") or ticker.get("fundingTime")
                                   or ticker.get("info", {}).get("nextFundingTime") or -0,
            }

            if data["last"] is None or data["last"] <= 0:
                logger.warning(f"{ex_name} {symbol} 无效价格，跳过")
                await asyncio.sleep(5)
                continue

            # 统一 WS 推送格式
            await ws.send_json({
                "code": 0,
                "msg": "success",
                "data": data,
                "ts": ex.milliseconds()
            })

        except ccxt.BadSymbol as e:
            # ❌ 不支持的 symbol —— 不可恢复
            logger.warning(f"{ex_name} {symbol} 不存在: {e}")
            if ws.client_state.name == "CONNECTED":
                await ws.send_json({
                    "code": 4002,
                    "msg": f"symbol not supported: {symbol}",
                    "data": None,
                    "ts": ex.milliseconds()
                })
            break  # 直接结束这个 symbol 的 task

        except WebSocketDisconnect:
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