from fastapi import APIRouter, Query
import ccxt.async_support as ccxt_async  # 使用异步版本
import logging
from datetime import datetime  # 用于 fallback ts

logger = logging.getLogger(__name__)

router = APIRouter()

# 定义主流币基础报价货币（优先排前）
MAJOR_BASES = {
    "USDT", "USDC", "USD", "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX", "FDUSD",
}


@router.get("/pairs")
async def get_pairs(
    exchange: str = Query(
        "binance",
        description="交易所名称（小写），如 binance, okx, bybit, gate, kraken",
        example="binance",
    ),
    market: str = Query(
        "all",
        description="市场类型：all（全部并分组，默认）、spot（仅现货）、future（仅合约）、option（仅期权）",
        example="all",
    ),
    page: int = Query(1, ge=1, description="页码（仅单组模式有效）"),
    page_size: int = Query(100, ge=1, le=500, description="每页数量（仅单组模式有效）"),
):
    try:
        exchange_id = exchange.lower().strip()
        ex_class = getattr(ccxt_async, exchange_id)
        if not ex_class:
            raise AttributeError(f"不支持的交易所: '{exchange}'")

        # 使用 async with 管理异步实例，自动关闭连接
        async with ex_class({'enableRateLimit': True}) as ex:
            # 异步加载市场信息
            await ex.load_markets()

            # 尝试异步获取 tickers 用于交易量排序（很多交易所支持）
            try:
                tickers = await ex.fetch_tickers()
            except Exception:
                tickers = {}

            groups = {"spot": [], "future": [], "option": []}
            for symbol, market_info in ex.markets.items():
                if market_info.get("active") is False:
                    continue

                m_type = market_info.get("type", "spot")
                if m_type in ["swap", "perpetual", "future", "delivery"]:
                    normalized_type = "future"
                elif m_type in ["option", "options"]:
                    normalized_type = "option"
                else:
                    normalized_type = "spot"

                ticker = tickers.get(symbol, {})
                # 优先使用 baseVolume，其次 quoteVolume
                volume = ticker.get("baseVolume") or ticker.get("quoteVolume") or 0

                groups[normalized_type].append(
                    {
                        "symbol": symbol,
                        "type": normalized_type,
                        "volume": volume,
                        "base": market_info.get("base"),
                        "quote": market_info.get("quote"),
                    }
                )

            # 智能排序函数（主流报价币 > 主流基础币 > 交易量降序 > 符号字母序）
            def sort_key(item):
                quote_priority = 0 if item["quote"] in MAJOR_BASES else 1
                base_priority = 0 if item["base"] in MAJOR_BASES else 1
                volume_score = -(item["volume"] or 0)
                return (quote_priority, base_priority, volume_score, item["symbol"])

            # 每组内排序
            for key in groups:
                groups[key].sort(key=sort_key)

            # ==========================
            # 构建返回结果（核心逻辑不变）
            # ==========================
            result = {"spot": [], "future": [], "option": []}
            available_groups = []
            total = 0
            current_id = 1

            if market == "all":
                for g_type, pair_list in groups.items():
                    if pair_list:
                        available_groups.append(g_type)
                    for item in pair_list:
                        result[g_type].append(
                            {
                                "id": current_id,
                                "exchange": exchange_id,
                                "pair": item["symbol"],
                                "active": True,
                                "type": item["type"],
                                "route": f"https://www.{exchange_id}.com",
                            }
                        )
                        current_id += 1
                        total += 1
                mode = "grouped"
                extra = {"groups": available_groups, "mode": mode}
            else:
                if market not in groups:
                    raise ValueError(f"不支持的市场类型: '{market}'")
                pair_list = groups[market]
                if pair_list:
                    available_groups.append(market)
                total_all_in_group = len(pair_list)
                start = (page - 1) * page_size
                end = start + page_size
                paginated = pair_list[start:end]
                for item in paginated:
                    result[market].append(
                        {
                            "id": current_id,
                            "exchange": exchange_id,
                            "pair": item["symbol"],
                            "active": True,
                            "type": item["type"],
                            "route": f"https://www.{exchange_id}.com",
                        }
                    )
                    current_id += 1
                total = len(result[market])
                mode = "single"
                extra = {
                    "groups": available_groups,
                    "page": page if total > 0 else None,
                    "page_size": page_size if total > 0 else None,
                    "market": market,
                    "mode": mode,
                }

            # 统一返回结构
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "result": result,
                    "exchange": exchange_id,
                    "total": total,
                    **extra
                },
                "ts": int(ex.milliseconds())
            }

    except AttributeError as e:
        logger.error(f"Pairs REST AttributeError: {str(e)}")
        return {
            "code": 4001,
            "msg": f"不支持的交易所: '{exchange}'",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except ccxt.BadSymbol as e:
        logger.error(f"Pairs REST BadSymbol: {str(e)}")
        return {
            "code": 4002,
            "msg": f"无效的交易对或市场类型: {str(e)}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }

    except Exception as e:
        logger.error(f"Pairs REST 异常: {str(e)}")
        return {
            "code": 5000,
            "msg": str(e),
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }