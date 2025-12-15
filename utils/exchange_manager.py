import ccxt.async_support as ccxt_async


#  方案B和C可以完美支持异步接口
class ExchangeManager:
    _instances = {}

    @classmethod
    async def get_exchange(cls, exchange_id: str):
        exchange_id = exchange_id.lower()
        if exchange_id not in cls._instances:
            ex_class = getattr(ccxt_async, exchange_id)

            # 💡 针对异步版的终极代理配置
            proxy_url = "http://127.0.0.1:7890"
            config = {
                "enableRateLimit": True,
                # 方案 A: 标准 proxies
                # "proxies": {
                #     "http": proxy_url,
                #     "https": proxy_url,
                # },
                # # 方案 B: 强制指定 aiohttp 代理（有些环境只认这个）
                "aiohttp_proxy": proxy_url,
                # 方案 C: CCXT 内部属性
                # "httpsProxy": proxy_url,
                "options": {"defaultType": "spot"},
                "timeout": 30000,
            }

            instance = ex_class(config)
            # 预热：这一步会检查代理是否通畅
            await instance.load_markets()
            cls._instances[exchange_id] = instance

        return cls._instances[exchange_id]
