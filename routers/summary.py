from fastapi import APIRouter, Query
import ccxt.async_support as ccxt_async  # ← 异步版
import asyncio
import logging
from datetime import datetime  # 用于 fallback ts

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/summary")
async def get_pair_summary(
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
):
    """
    异步版本的 /summary 接口，完全兼容旧 CryptoWatch 结构
    使用 ccxt.async_support，避免阻塞事件循环
    返回统一结构：{"code": 0, "msg": "success", "data": {"result": {...}}, "ts": ...}
    """
    exchange = exchange.lower().strip()
    symbol = symbol.upper().strip()
    ex: ccxt_async.Exchange | None = None

    try:
        ex_class = getattr(ccxt_async, exchange, None)
        if not ex_class:
            raise AttributeError(f"不支持的交易所: '{exchange}'")

        ex = ex_class({'enableRateLimit': True})  # 建议加限速

        # 异步加载市场数据（关键！避免 symbol 映射错误）
        await ex.load_markets()

        if symbol not in ex.markets:
            raise ccxt_async.BadSymbol(f"无效的交易对: '{symbol}' 在 {exchange} 不存在或未激活")

        market = ex.markets[symbol]
        standardized_symbol = market["symbol"]

        # 异步获取 ticker
        ticker = await ex.fetch_ticker(standardized_symbol)

        # 可选：校验返回的 symbol 是否匹配（防御性编程）
        returned_symbol = ticker.get("symbol")
        if returned_symbol and returned_symbol != standardized_symbol:
            logger.warning(
                "[WARNING] %s ticker symbol 不匹配: 请求 %s, 返回 %s",
                exchange, standardized_symbol, returned_symbol
            )

        result = {
            "symbol": standardized_symbol,
            "price": {
                "last": ticker.get("last"),
                "high": ticker.get("high"),
                "low": ticker.get("low"),
                "change": {
                    "percentage": ticker.get("percentage"),
                    "absolute": ticker.get("change"),
                },
            },
            "volume": ticker.get("baseVolume") or ticker.get("volume") or 0.0,
            "volumeQuote": ticker.get("quoteVolume") or 0.0,
            "timestamp": ticker.get("timestamp")
                         or int(asyncio.get_event_loop().time() * 1000),
        }

        # 统一返回结构
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "result": result
            },
            "ts": int(ex.milliseconds())
        }

    except AttributeError as e:
        logger.error(f"Summary REST AttributeError: {str(e)}")
        return {
            "code": 4001,
            "msg": f"不支持的交易所: '{exchange}'",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except ccxt_async.BadSymbol as e:
        logger.error(f"Summary REST BadSymbol: {str(e)}")
        return {
            "code": 4002,
            "msg": f"无效的交易对: '{symbol}' 在 {exchange} 不存在",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except ccxt_async.ExchangeError as e:
        logger.error(f"Summary REST ExchangeError: {str(e)}")
        return {
            "code": 5001,
            "msg": f"交易所错误: {str(e)}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except Exception as e:
        logger.error(f"Summary REST 未知错误: {str(e)}")
        return {
            "code": 5000,
            "msg": f"未知错误: {str(e)}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    finally:
        # 【重要】异步版本必须关闭连接，防止连接泄漏
        if ex is not None:
            await ex.close()