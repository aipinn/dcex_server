from fastapi import APIRouter, Query
import ccxt
import logging
from datetime import datetime  # 用于 fallback ts

logger = logging.getLogger(__name__)

router = APIRouter()  # 创建路由器


@router.get("/trades")
async def get_trades(
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
        description="返回成交记录数量，最大视交易所而定（通常 100-1000）",
        example=100,
    ),
):
    """
    完全兼容旧 CryptoWatch 的 /markets/{exchange}/{pair}/trades 接口
    返回统一结构：{"code": 0, "msg": "success", "data": {"result": [[...], ...]}, "ts": ...}
    """
    try:
        exchange = exchange.lower().strip()
        ex_class = getattr(ccxt, exchange)
        ex = ex_class({'enableRateLimit': True})  # 建议加限速，避免被 ban

        trades = ex.fetch_trades(symbol, limit=limit)

        # 构造 CryptoWatch 风格的 result 数组（核心逻辑不变）
        # [id, timestamp, price, amount, side] 全转字符串（兼容你的 Trade.fromJson(List<dynamic>))
        result = [
            [
                str(trade["id"]) if trade["id"] is not None else "",
                str(trade["timestamp"]),
                str(trade["price"]),
                str(trade["amount"]),
                str(trade["side"]),  # buy or sell
            ]
            for trade in trades
        ]

        logger.info("🌈 trades query params: %s %s %s (fetched %d trades)", exchange, symbol, limit, len(trades))

        # 统一返回结构
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "result": result,
                "symbol": symbol,  # 可选加回，便于客户端确认
            },
            "ts": int(ex.milliseconds())
        }

    except AttributeError:
        return {
            "code": 4001,
            "msg": f"不支持的交易所: '{exchange}'",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except ccxt.BadSymbol:
        return {
            "code": 4002,
            "msg": f"无效的交易对: '{symbol}' 在 {exchange} 不存在",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except ccxt.NetworkError as e:
        return {
            "code": 5001,
            "msg": f"网络错误: {str(e)}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except Exception as e:
        logger.error(f"trades REST 异常: {str(e)}")
        return {
            "code": 5000,
            "msg": str(e),
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }