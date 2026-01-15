from fastapi import APIRouter, Query
import ccxt.async_support as ccxt_async
import asyncio
from typing import Dict, Any
import logging
from datetime import datetime  # 用于 fallback ts

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ticker")
async def get_pair_ticker(
    exchange: str = Query(
        "binance",
        description="交易所名称（小写），如 binance, okx, bybit, gate, kraken",
        example="binance",
    ),
    symbol: str = Query(
        "BTC/USDT",
        description="交易对（CCXT 标准格式，大写带斜杠），如 BTC/USDT, ETH/USDT:USDT",
        example="BTC/USDT",
    ),
    market_type: str = Query(
        "spot",
        description="市场类型: spot, perpetual, delivery, option, margin",
        enum=["spot", "perpetual", "delivery", "option", "margin"],
        example="spot",
    ),
):
    """
    获取交易对汇总信息（Ticker / Summary）
    返回结构兼容旧 CryptoWatch 风格，同时包含完整的 Ticker 数据模型
    统一响应格式：{"code": 0, "msg": "success", "data": {"result": {...}}, "ts": ...}
    """
    exchange = exchange.lower().strip()
    symbol = symbol.upper().strip()
    market_type = market_type.lower().strip()
    ex: ccxt_async.Exchange | None = None

    try:
        # 获取交易所类
        ex_class = getattr(ccxt_async, exchange, None)
        if not ex_class:
            raise AttributeError(f"不支持的交易所: '{exchange}'")

        # 配置：设置 defaultType
        config = {
            "enableRateLimit": True,
            "options": {"defaultType": market_type},
        }
        ex = ex_class(config)

        # 异步加载市场
        await ex.load_markets()

        # 标准化 symbol（防御性）
        if symbol not in ex.markets:
            raise ccxt_async.BadSymbol(f"无效的交易对: '{symbol}' 在 {exchange} 不存在或未激活")

        market = ex.markets[symbol]
        standardized_symbol = market["symbol"]

        # 获取 ticker（异步）
        ticker_raw = await ex.fetch_ticker(standardized_symbol)

        # 根据 market_type 构建不同的 Ticker 数据（核心逻辑不变）
        ticker_data: Dict[str, Any] = {
            "symbol": standardized_symbol,
            "last": ticker_raw.get("last"),
            "open": ticker_raw.get("open"),
            "high": ticker_raw.get("high"),
            "low": ticker_raw.get("low"),
            "bid": ticker_raw.get("bid"),
            "ask": ticker_raw.get("ask"),
            "change": ticker_raw.get("change"),
            "percentage": ticker_raw.get("percentage"),
            "baseVolume": ticker_raw.get("baseVolume") or 0.0,
            "quoteVolume": ticker_raw.get("quoteVolume") or 0.0,
            "timestamp": ticker_raw.get("timestamp")
                         or int(asyncio.get_event_loop().time() * 1000),
            "vwap": ticker_raw.get("vwap"),
            "info": ticker_raw.get("info", {}),  # 保留原始数据
            "marketType": market_type,
        }

        # 补充衍生品特有字段
        if market_type in ["perpetual", "delivery"]:
            ticker_data.update({
                "markPrice": ticker_raw.get("markPrice"),
                "indexPrice": ticker_raw.get("indexPrice"),
                "fundingRate": ticker_raw.get("fundingRate"),
                "nextFundingTime": ticker_raw.get("nextFundingTime"),
            })
        elif market_type == "option":
            ticker_data.update({
                "strikePrice": ticker_raw.get("strike"),  # 部分交易所字段名
                "expiryDate": ticker_raw.get("expiry"),
                # 注意：期权类型（call/put）通常在 symbol 中解析，此处简化为字符串
                "optionType": "call" if "C" in standardized_symbol.upper() else "put",
                "impliedVolatility": ticker_raw.get("impliedVolatility"),
            })

        # 兼容旧格式（可选保留）
        result = {
            "symbol": standardized_symbol,
            "marketType": market_type,
            "ticker": ticker_data,
            "price": {
                "last": ticker_data["last"],
                "high": ticker_data["high"],
                "low": ticker_data["low"],
                "change": {
                    "percentage": ticker_data["percentage"],
                    "absolute": ticker_data["change"],
                },
            },
            "volume": ticker_data["baseVolume"],
            "volumeQuote": ticker_data["quoteVolume"],
            "timestamp": ticker_data["timestamp"],
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
        logger.error(f"Ticker REST AttributeError: {str(e)}")
        return {
            "code": 4001,
            "msg": f"不支持的交易所: '{exchange}'",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except ccxt_async.BadSymbol as e:
        logger.error(f"Ticker REST BadSymbol: {str(e)}")
        return {
            "code": 4002,
            "msg": f"无效的交易对: '{symbol}' 在 {exchange} 不存在",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except ccxt_async.ExchangeError as e:
        logger.error(f"Ticker REST ExchangeError: {str(e)}")
        return {
            "code": 5001,
            "msg": f"交易所错误: {str(e)}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except Exception as e:
        logger.error(f"Ticker REST 未知错误: {str(e)}")
        return {
            "code": 5000,
            "msg": f"未知错误: {str(e)}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    finally:
        if ex is not None:
            await ex.close()