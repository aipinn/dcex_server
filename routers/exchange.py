from fastapi import APIRouter
import ccxt.async_support as ccxt_async  # 改为异步版本（推荐统一使用 async）
import logging
from datetime import datetime  # 用于 ts

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/exchanges")
async def get_exchanges():
    """
    完全兼容旧 CryptoWatch 的 /exchanges 接口
    返回交易所列表，结构匹配旧 Exchange 模型
    统一响应格式：{"code": 0, "msg": "success", "data": {"result": [...]}, "ts": ...}
    """
    try:
        # CCXT 支持的交易所列表（小写，已排序）
        supported_exchanges = sorted(ccxt_async.exchanges)  # 使用 ccxt_async 保持一致

        # 手动映射主流交易所的显示名称和官网（更友好）
        name_map = {
            "binance": "Binance",
            "okx": "OKX",
            "bybit": "Bybit",
            "gate": "Gate.io",
            "kraken": "Kraken",
            "huobi": "Huobi",
            "kucoin": "KuCoin",
            "bitget": "Bitget",
            "mexc": "MEXC",
            "coinbase": "Coinbase Pro",
        }

        route_map = {
            "binance": "https://www.binance.com",
            "okx": "https://www.okx.com",
            "bybit": "https://www.bybit.com",
            "gate": "https://www.gate.io",
            "kraken": "https://www.kraken.com",
            "huobi": "https://www.huobi.com",
            "kucoin": "https://www.kucoin.com",
            "bitget": "https://www.bitget.com",
            "mexc": "https://www.mexc.com",
            "coinbase": "https://pro.coinbase.com",
        }

        result = []
        for idx, symbol in enumerate(supported_exchanges, start=1):
            result.append(
                {
                    "id": idx,  # 从 1 开始递增的整数 ID
                    "symbol": symbol,
                    "name": name_map.get(symbol, symbol.capitalize()),
                    "route": route_map.get(symbol, f"https://www.{symbol}.com"),
                    "active": True,  # CCXT 支持的交易所均视为 active
                }
            )

        # 统一返回结构
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "result": result,
                "total": len(result),
                "source": "ccxt"  # 可选：标明数据来源
            },
            "ts": int(datetime.utcnow().timestamp() * 1000)  # 无需 ex 对象，用当前时间
        }

    except Exception as e:
        logger.error(f"Exchanges REST 异常: {str(e)}")
        return {
            "code": 5000,
            "msg": f"获取交易所列表失败: {str(e)}",
            "data": None,
            "ts": int(datetime.utcnow().timestamp() * 1000)
        }