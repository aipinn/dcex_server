from fastapi import APIRouter, Query
import ccxt.async_support as ccxt_async  # 注意：异步版本
import asyncio
import logging
from datetime import datetime  # 用于 fallback ts

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ohlc")
async def get_pair_ohlc(
    exchange: str = Query("binance", example="binance"),
    symbol: str = Query("BTC/USDT", example="BTC/USDT"),
    periods: str = Query(
        "3600", description="K线周期（秒），支持多个逗号分隔，如 60,3600"
    ),
    after: str = Query("", description="起始时间戳（秒）"),
    before: str = Query("", description="结束时间戳（秒）"),  # 注意：当前代码未使用 before，可后续扩展
):
    """
    异步版本的 /ohlc 接口
    使用 ccxt.async_support，避免阻塞事件循环
    返回统一结构：{"code": 0, "msg": "success", "data": {"result": {...}}, "ts": ...}
    """
    try:
        exchange_id = exchange.lower().strip()
        ex_class = getattr(ccxt_async, exchange_id)

        async with ex_class({'enableRateLimit': True}) as ex:  # 加限速，推荐
            period_list = [p.strip() for p in periods.split(",") if p.strip()]

            timeframe_map = {
                "60": "1m",
                "180": "3m",
                "300": "5m",
                "900": "15m",
                "1800": "30m",
                "3600": "1h",
                "7200": "2h",
                "14400": "4h",
                "86400": "1d",
                "604800": "1w",
            }

            since = None
            if after:
                since = int(after) * 1000  # 秒 → 毫秒

            # 并行获取多个周期的数据
            tasks = []
            for period in period_list:
                timeframe = timeframe_map.get(period, "1h")
                limit = 200
                task = ex.fetch_ohlcv(
                    symbol, timeframe=timeframe, since=since, limit=limit
                )
                tasks.append((period, task))

            results = await asyncio.gather(*[task for _, task in tasks])

            result = {}
            for (period, _), ohlcv in zip(tasks, results):
                result[period] = [
                    [
                        int(candle[0] / 1000),          # timestamp 秒
                        candle[1],                      # open
                        candle[2],                      # high
                        candle[3],                      # low
                        candle[4],                      # close
                        candle[5],                      # volume
                        round(candle[4] * candle[5], 2), # quoteVolume 近似计算
                    ]
                    for candle in ohlcv
                ]

            # 统一返回结构
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "result": result,
                    "symbol": symbol,
                    "exchange": exchange_id,
                },
                "ts": int(ex.milliseconds())
            }

    except AttributeError:
        logger.error(f"OHLC REST AttributeError: 不支持的交易所 '{exchange}'")
        return {
            "code": 4001,
            "msg": f"不支持的交易所: '{exchange}'",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except ccxt_async.BadSymbol:
        logger.error(f"OHLC REST BadSymbol: 无效的交易对 '{symbol}' 在 {exchange}")
        return {
            "code": 4002,
            "msg": f"无效的交易对: '{symbol}' 在 {exchange} 不存在",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except ccxt_async.ExchangeError as e:
        logger.error(f"OHLC REST ExchangeError: {str(e)}")
        return {
            "code": 5001,
            "msg": f"交易所错误: {str(e)}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except Exception as e:
        logger.error(f"OHLC REST 异常: {str(e)}")
        return {
            "code": 5000,
            "msg": str(e),
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }