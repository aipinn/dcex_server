from fastapi import APIRouter, Query
import ccxt
import logging
from datetime import datetime  # 用于 fallback ts

logger = logging.getLogger(__name__)

router = APIRouter()  # 创建路由器


@router.get("/orderbook")
async def get_order_book(
    exchange: str = Query(
        "binance",
        description="交易所名称（小写），如 binance, okx, bybit, gate, kraken",
        example="binance",
    ),
    symbol: str = Query(
        "BTC/USDT",
        description="交易对（CCXT 标准格式，大写带斜杠），如 BTC/USDT, ETH/USDT",
        example="BTC/USDT",
    ),
    limit: int = Query(
        100,
        description="深度数量（每边 asks/bids），常见 5-100，最大视交易所而定",
        example=100,
    ),
):
    try:
        exchange = exchange.lower().strip()
        ex_class = getattr(ccxt, exchange)
        ex = ex_class({"enableRateLimit": True})  # 建议加限速，避免被 ban

        orderbook = ex.fetch_order_book(symbol, limit=limit)

        logger.info("🌈 orderbook query params: %s %s %s", exchange, symbol, limit)

        # 构造兼容旧模型的 data（核心数据部分不变）
        data = {
            "asks": [
                [float(price), float(amount)] for price, amount in orderbook["asks"]
            ],
            "bids": [
                [float(price), float(amount)] for price, amount in orderbook["bids"]
            ],
            "nonce": orderbook.get("nonce")
            or orderbook.get("sequence")
            or 0,  # 兼容不同交易所
            "timestamp": orderbook.get("timestamp") or int(ex.milliseconds()),
            "symbol": orderbook.get("symbol") or symbol,
            "exchange": exchange,
            "action": "fetch",
            "marketType": "",
        }

        # 统一返回结构
        return {
            "code": 0,
            "msg": "success",
            "data": data,
            "ts": int(ex.milliseconds()),  # 或用 datetime.utcnow().timestamp() * 1000
        }

    except AttributeError:
        return {
            "code": 4001,
            "msg": f"不支持的交易所: '{exchange}'",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000),
        }

    except ccxt.BadSymbol:
        return {
            "code": 4002,
            "msg": f"无效的交易对: '{symbol}' 在 {exchange} 不存在",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000),
        }

    except ccxt.NetworkError as e:
        return {
            "code": 5001,
            "msg": f"网络错误: {str(e)}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000),
        }

    except Exception as e:
        logger.error(f"orderbook REST 异常: {str(e)}")
        return {
            "code": 5000,
            "msg": str(e),
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000),
        }
