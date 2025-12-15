from fastapi import APIRouter, Query
import ccxt

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
    返回 {"result": [[id, timestamp, price, amount], ...]}
    """
    try:
        exchange = exchange.lower().strip()

        ex_class = getattr(ccxt, exchange)
        ex = ex_class()

        trades = ex.fetch_trades(symbol, limit=limit)

        # 构造 CryptoWatch 风格的 result 数组
        # [id, timestamp, price, amount] 全转字符串（兼容你的 Trade.fromJson(List<dynamic>))
        result = [
            [
                str(trade["id"]) if trade["id"] is not None else "",  # id
                str(trade["timestamp"]),  # timestamp (ms)
                str(trade["price"]),  # price
                str(trade["amount"]),  # amount
                str(trade["side"]),  # buy or sell
            ]
            for trade in trades
        ]

        return {"result": result}

    except AttributeError:
        return {"error": f"不支持的交易所: '{exchange}'"}
    except ccxt.BadSymbol:
        return {"error": f"无效的交易对: '{symbol}' 在 {exchange} 不存在"}
    except Exception as e:
        return {"error": str(e)}
