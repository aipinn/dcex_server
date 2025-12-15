from fastapi import APIRouter, Query
import ccxt
import logging

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
        ex = ex_class()

        orderbook = ex.fetch_order_book(symbol, limit=limit)
        logger.info("🌈 orderbook query params: %s %s %s", exchange, symbol, limit)

        # 构造兼容旧模型的 result
        result = {
            "asks": [
                [float(price), float(amount)] for price, amount in orderbook["asks"]
            ],
            "bids": [
                [float(price), float(amount)] for price, amount in orderbook["bids"]
            ],
            "seqNum": orderbook.get("nonce")
            or orderbook.get("sequence")
            or 0,  # 兼容不同交易所
            "timestamp": orderbook.get("timestamp") or int(ex.milliseconds()),  #
            "symbol": orderbook.get("symbol") or symbol,
        }

        return {"result": result}

    except AttributeError:
        return {"error": f"不支持的交易所: '{exchange}'"}
    except ccxt.BadSymbol:
        return {"error": f"无效的交易对: '{symbol}' 在 {exchange} 不存在"}
    except Exception as e:
        return {"error": str(e)}
