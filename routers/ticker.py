from fastapi import APIRouter, Query
import ccxt

router = APIRouter()  # 创建路由器


# 定义一个 GET 接口，路径是 /ticker。
@router.get("/ticker")
# 接口函数名随意，这里叫 get_ticker。
# 两个参数都是从 URL 查询参数（?key=value）里取：
# symbol：默认 BTC/USDT
# exchange：默认 binance
# Query(...) 里写了默认值和中文描述（会在 /docs 页面显示，很人性化）
async def get_ticker(
    symbol: str = Query("BTC/USDT", description="交易对，如 BTC/USDT"),
    exchange: str = Query(
        "binance", description="交易所：binance, okx, bybit, gate 等"
    ),
):
    try:
        # 动态创建交易所实例
        # 核心部分：用 getattr(ccxt, exchange) 动态获取对应交易所的类（比如 exchange="binance" → ccxt.binance）。
        ex_class = getattr(ccxt, exchange)
        # 创建实例时开启 enableRateLimit=True，CCXT 会自动控制请求频率，避免你的 IP 或服务器被交易所临时封禁。
        ex = ex_class()

        # 调用 CCXT 的统一方法 fetch_ticker，获取该交易对的最新 ticker 数据（包含价格、最高、最低、成交量等几十个字段）。
        ticker = ex.fetch_ticker(symbol)
        # 只挑了几个常用字段返回，保持响应简洁。你可以根据需要加更多，比如 ticker['volume']（成交量）等。
        return {
            "exchange": exchange,
            "symbol": symbol,
            "price": ticker["last"],
            "high": ticker["high"],
            "low": ticker["low"],
            "timestamp": ticker["timestamp"],
        }
    # 任何错误（交易所名写错、网络问题、交易对不存在等）都会捕获，返回错误信息，不会让 API 直接崩溃。
    except Exception as e:
        return {"error": str(e)}
