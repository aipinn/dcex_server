from fastapi import APIRouter, Query
import ccxt.async_support as ccxt  # 使用异步版本

router = APIRouter()

# 定义主流币基础报价货币（优先排前）
MAJOR_BASES = {
    "USDT",
    "USDC",
    "USD",
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "ADA",
    "DOGE",
    "TRX",
    "FDUSD",
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
        ex_class = getattr(ccxt, exchange_id)
        if not ex_class:
            return {"error": f"不支持的交易所: '{exchange}'"}

        # 使用 async with 管理异步实例，自动关闭连接
        async with ex_class() as ex:
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
            # 构建返回结果
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
                    return {"error": f"不支持的市场类型: '{market}'"}

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
                else:
                    total = 0

                mode = "single"
                extra = {
                    "groups": available_groups,
                    "page": page if total > 0 else None,
                    "page_size": page_size if total > 0 else None,
                    "market": market,
                    "mode": mode,
                }

            return {"result": result, "exchange": exchange_id, "total": total, **extra}

    except AttributeError:
        return {"error": f"不支持的交易所: '{exchange}'"}
    except Exception as e:
        return {"error": str(e)}


# from fastapi import APIRouter, Query
# import ccxt

# router = APIRouter()

# # 定义主流币基础报价货币（这些币的交易对优先排前）
# MAJOR_BASES = {
#     "USDT",
#     "USDC",
#     "USD",
#     "BTC",
#     "ETH",
#     "BNB",
#     "SOL",
#     "XRP",
#     "ADA",
#     "DOGE",
#     "TRX",
#     "FDUSD",
# }

# # 可选：进一步定义顶级交易对，手动置顶（如果需要绝对控制前几名）
# # TOP_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", ...]  # 如果想绝对置顶可打开


# @router.get("/pairs")
# async def get_pairs(
#     exchange: str = Query(
#         "binance",
#         description="交易所名称（小写），如 binance, okx, bybit, gate, kraken",
#         example="binance",
#     ),
#     market: str = Query(
#         "all",
#         description="市场类型：all（全部并分组，默认）、spot（仅现货）、future（仅合约）、option（仅期权）",
#         example="all",
#     ),
#     page: int = Query(1, ge=1, description="页码（仅单组模式有效）"),
#     page_size: int = Query(100, ge=1, le=500, description="每页数量（仅单组模式有效）"),
# ):
#     try:
#         exchange = exchange.lower().strip()
#         ex_class = getattr(ccxt, exchange)
#         if not ex_class:
#             return {"error": f"不支持的交易所: '{exchange}'"}

#         ex = ex_class()
#         ex.load_markets()

#         # 可选：加载 ticker 获取交易量（推荐！排序更准确）
#         # 注意：有些交易所 load_markets 后 markets 已有 volume，有些没有
#         try:
#             tickers = ex.fetch_tickers()
#         except Exception:
#             tickers = {}

#         groups = {"spot": [], "future": [], "option": []}

#         for symbol, market_info in ex.markets.items():
#             if market_info.get("active") is False:
#                 continue

#             m_type = market_info.get("type", "spot")
#             if m_type in ["swap", "perpetual", "future", "delivery"]:
#                 normalized_type = "future"
#             elif m_type in ["option", "options"]:
#                 normalized_type = "option"
#             else:
#                 normalized_type = "spot"

#             # 获取交易量（24h baseVolume 或 quoteVolume）
#             ticker = tickers.get(symbol, {})
#             volume = ticker.get("baseVolume") or ticker.get("quoteVolume") or 0

#             groups[normalized_type].append(
#                 {
#                     "symbol": symbol,
#                     "type": normalized_type,
#                     "volume": volume,  # 用于排序
#                     "base": market_info.get("base"),  # 如 "BTC"
#                     "quote": market_info.get("quote"),  # 如 "USDT"
#                 }
#             )

#         # 智能排序函数
#         def sort_key(item):
#             symbol = item["symbol"]
#             base = item["base"]
#             quote = item["quote"]
#             volume = item["volume"] or 0

#             # 优先级1：主流报价货币（如 USDT, USDC）优先
#             quote_priority = 0 if quote in MAJOR_BASES else 1

#             # 优先级2：主流基础货币（如 BTC, ETH）优先
#             base_priority = 0 if base in MAJOR_BASES else 1

#             # 优先级3：交易量降序（越大越前）
#             volume_score = -volume  # 负数实现降序

#             # 优先级4：symbol 字母顺序（兜底）
#             symbol_score = symbol

#             return (quote_priority, base_priority, volume_score, symbol_score)

#         # 对每个组内进行智能排序
#         for key in groups:
#             groups[key].sort(key=sort_key)

#         # ==========================
#         # 构建返回结果
#         # ==========================
#         result = {"spot": [], "future": [], "option": []}
#         available_groups = []
#         total = 0
#         current_id = 1

#         if market == "all":
#             for g_type, pair_list in groups.items():
#                 if pair_list:
#                     available_groups.append(g_type)
#                 for item in pair_list:
#                     result[g_type].append(
#                         {
#                             "id": current_id,
#                             "exchange": exchange,
#                             "pair": item["symbol"],
#                             "active": True,
#                             "type": item["type"],
#                             "route": f"https://www.{exchange}.com",
#                         }
#                     )
#                     current_id += 1
#                     total += 1
#             mode = "grouped"
#             extra = {"groups": available_groups, "mode": mode}

#         else:
#             if market not in groups:
#                 return {"error": f"不支持的市场类型: '{market}'"}
#             pair_list = groups[market]
#             available_groups.append(market)

#             if pair_list:
#                 total_all_in_group = len(pair_list)
#                 start = (page - 1) * page_size
#                 end = start + page_size
#                 paginated = pair_list[start:end]

#                 for item in paginated:
#                     result[market].append(
#                         {
#                             "id": current_id,
#                             "exchange": exchange,
#                             "pair": item["symbol"],
#                             "active": True,
#                             "type": item["type"],
#                             "route": f"https://www.{exchange}.com",
#                         }
#                     )
#                     current_id += 1
#                 total = len(result[market])
#             else:
#                 total = 0

#             mode = "single"
#             extra = {
#                 "groups": available_groups,
#                 "page": page if total > 0 else None,
#                 "page_size": page_size if total > 0 else None,
#                 "market": market,
#                 "mode": mode,
#             }

#         return {"result": result, "exchange": exchange, "total": total, **extra}

#     except AttributeError:
#         return {"error": f"不支持的交易所: '{exchange}'"}
#     except Exception as e:
#         return {"error": str(e)}


# @router.get("/pairs")
# async def get_pairs(
#     exchange: str = Query(
#         "binance",
#         description="交易所名称（小写），如 binance, okx, bybit, gate, kraken",
#         example="binance",
#     ),
#     page: int = Query(1, ge=1, description="页码，从 1 开始", example=1),
#     page_size: int = Query(
#         100, ge=1, le=500, description="每页数量，最大 500", example=100
#     ),
# ):
#     try:
#         exchange = exchange.lower().strip()
#         ex_class = getattr(ccxt, exchange)
#         ex = ex_class()

#         ex.load_markets()

#         # 提取活跃交易对并排序
#         temp_pairs = []
#         for symbol, market in ex.markets.items():
#             if market.get("active") is not False:
#                 temp_pairs.append(
#                     {
#                         "symbol": symbol,  # CCXT 标准 "BTC/USDT"
#                         "active": market.get("active", True),
#                     }
#                 )

#         temp_pairs.sort(key=lambda x: x["symbol"])

#         # 分页
#         total = len(temp_pairs)
#         start = (page - 1) * page_size
#         end = start + page_size
#         paginated = temp_pairs[start:end]

#         # 转换为旧 Pair 模型兼容格式
#         pairs = []
#         for idx, item in enumerate(paginated, start=(page - 1) * page_size + 1):
#             pairs.append(
#                 {
#                     "id": idx,
#                     "exchange": exchange,  # 每个项都带上（虽然有默认值）
#                     "pair": item["symbol"],  # 关键：用 "symbol" 字段映射到 Dart 的 pair
#                     "active": item["active"],
#                     "route": f"https://www.{exchange}.com",
#                 }
#             )

#         return {
#             "result": pairs,  # ← 关键字段名
#             "exchange": exchange,  # 默认值
#             # 可选分页信息（Flutter 端可忽略）
#             "page": page,
#             "page_size": page_size,
#             "total": total,
#         }

#     except AttributeError:
#         return {"error": f"不支持的交易所: '{exchange}'"}
#     except Exception as e:
#         return {"error": str(e)}


# 端上给默认值适配
# @router.get("/pairs")
# async def get_pairs(
#     exchange: str = Query("binance", description="交易所小写名称"),
#     page: int = Query(1, ge=1, description="页码，从 1 开始"),
#     page_size: int = Query(100, ge=1, le=500, description="每页数量，最大 500"),
# ):
#     try:
#         exchange = exchange.lower().strip()
#         ex_class = getattr(ccxt, exchange)
#         ex = ex_class()

#         ex.load_markets()

#         # 提取所有活跃交易对
#         pairs = []
#         for symbol, market in ex.markets.items():
#             if market.get("active") is not False:  # 包括 True 和 None
#                 pairs.append(
#                     {
#                         "symbol": symbol,
#                         "base": market["base"],
#                         "quote": market["quote"],
#                         "precision": market.get("precision", {}),
#                         "limits": market.get("limits", {}),
#                         "type": market.get("type", "spot"),
#                         "spot": market.get("spot", True),
#                         "active": market.get("active", True),
#                     }
#                 )

#         # 排序（按 symbol 字母序，稳定）
#         pairs.sort(key=lambda x: x["symbol"])

#         # 分页计算
#         total = len(pairs)
#         start = (page - 1) * page_size
#         end = start + page_size
#         paginated_pairs = pairs[start:end]

#         return {
#             "exchange": exchange,
#             "page": page,
#             "page_size": page_size,
#             "total": total,
#             "total_pages": (total + page_size - 1) // page_size,  # 向上取整
#             "pairs": paginated_pairs,
#         }

#     except AttributeError:
#         return {"error": f"不支持的交易所: '{exchange}'"}
#     except Exception as e:
#         return {"error": str(e)}
