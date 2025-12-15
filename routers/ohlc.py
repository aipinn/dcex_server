from fastapi import APIRouter, Query
import ccxt.async_support as ccxt  # 注意：异步版本
import asyncio

router = APIRouter()  # 创建路由器


@router.get("/ohlc")
async def get_pair_ohlc(
    exchange: str = Query("binance", example="binance"),
    symbol: str = Query("BTC/USDT", example="BTC/USDT"),
    periods: str = Query(
        "3600", description="K线周期（秒），支持多个逗号分隔，如 60,3600"
    ),
    after: str = Query("", description="起始时间戳（秒）"),
    before: str = Query(
        "", description="结束时间戳（秒）"
    ),  # 注意：当前代码未使用 before，可后续扩展
):
    """
    异步版本的 /ohlc 接口
    使用 ccxt.async_support，避免阻塞事件循环
    """
    try:
        exchange_id = exchange.lower().strip()
        ex_class = getattr(ccxt, exchange_id)

        async with ex_class() as ex:  # 使用 async with 自动关闭连接
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
                        int(candle[0] / 1000),  # timestamp 秒
                        candle[1],  # open
                        candle[2],  # high
                        candle[3],  # low
                        candle[4],  # close
                        candle[5],  # volume
                        round(candle[4] * candle[5], 2),  # quoteVolume 近似计算
                    ]
                    for candle in ohlcv
                ]

            return {"result": result}

    except AttributeError:
        return {"error": f"不支持的交易所: '{exchange}'"}
    except ccxt.BadSymbol:
        return {"error": f"无效的交易对: '{symbol}' 在 {exchange} 不存在"}
    except Exception as e:
        return {"error": str(e)}
