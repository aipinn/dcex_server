from fastapi import APIRouter
import ccxt.async_support as ccxt  # 改为导入异步版本（推荐用于 async def）

router = APIRouter()

@router.get("/exchanges")
async def get_exchanges():
    """
    完全兼容旧 CryptoWatch 的 /exchanges 接口
    返回交易所列表，结构匹配旧 Exchange 模型
    """
    # CCXT 支持的交易所列表（小写，已排序）
    supported_exchanges = sorted(ccxt.exchanges)

    # 手动映射主流交易所的显示名称和官网（更友好）
    name_map = {
        "binance": "Binance",
        "okx": "OKX",
        "bybit": "Bybit",
        "gate": "Gate.io",          # 修正：去掉 Markdown 链接，直接显示名称
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

    return {"result": result}