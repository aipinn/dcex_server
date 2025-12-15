from fastapi import APIRouter
import ccxt

router = APIRouter()  # 创建路由器


# 可选：返回所有支持的交易所列表（方便客户端选择）
@router.get("/exchanges")
async def get_exchanges():
    """
    完全兼容旧 CryptoWatch 的 /exchanges 接口
    返回交易所列表，结构匹配旧 Exchange 模型
    """
    # CCXT 支持的交易所列表（小写）
    supported_exchanges = sorted(ccxt.exchanges)

    # 手动映射一些主流交易所的显示名称和官网（可选，更友好）
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
                "id": idx,  # 旧模型需要 int id，从 1 开始递增
                "symbol": symbol,
                "name": name_map.get(symbol, symbol.capitalize()),
                "route": route_map.get(symbol, f"https://www.{symbol}.com"),
                "active": True,  # CCXT 支持的都视为 active
            }
        )

    return {"result": result}
