# # utils/ccxt_patch.py  或 main.py 顶部

# # import ccxt

# # 基础版本，支持同步的API
# # def apply_global_ccxt_patch():
# #     original_init = ccxt.Exchange.__init__

# #     def patched_init(self, *args, **kwargs):
# #         # ‼️‼️‼️先调用原始 init（只传原始参数，避免意外关键字报错）‼️‼️‼️
# #         original_init(self, *args, **kwargs)

# #         # 实例创建成功后，手动强制设置选项（所有交易所都支持这种方式）
# #         self.enableRateLimit = True  # 开启限速
# #         self.proxies = {  # 设置代理
# #             "http": "http://127.0.0.1:7890",
# #             "https": "http://127.0.0.1:7890",
# #         }

# #         # 可选：开启详细 HTTP 日志调试
# #         # self.verbose = True

# #     ccxt.Exchange.__init__ = patched_init


import ccxt
import ccxt.async_support as ccxt_async
import ccxt.pro as ccxt_pro  # 必须导入 pro 才能对其打补丁


# 同时支持同步和异步的REST API 和 WebSocket
def apply_global_ccxt_patch():
    proxy_url = "http://127.0.0.1:7890"

    def patch_factory(original_init, mode: str):
        def patched_init(self, config=None):
            if config is None:
                config = {}

            # 1. 基础公共配置
            config.setdefault("enableRateLimit", True)

            config.setdefault("timeout", 60000)

            # 2. 根据模式注入互斥的代理参数
            if mode == "sync":
                # 同步版 ccxt 使用原生的 proxies 结构
                config.setdefault(
                    "proxies",
                    {
                        "http": proxy_url,
                        "https": proxy_url,
                    },
                )
            else:
                # 异步 (ccxt_async) 和 Pro (ccxt_pro) 使用新的属性映射
                # 这样可以避开 "conflicting proxy settings" 错误
                # config.setdefault("httpsProxy", proxy_url)
                config.setdefault("aiohttp_proxy", proxy_url)

                # 注入 WebSocket 专用配置
                if mode == "pro":
                    if "options" not in config:
                        config["options"] = {}
                    if "ws" not in config["options"]:
                        config["options"]["ws"] = {}
                    config["options"]["ws"].setdefault("proxy", proxy_url)

            # 统一设置默认交易类型
            if "options" not in config:
                config["options"] = {}
            config["options"].setdefault("defaultType", "spot")

            original_init(self, config)

        return patched_init

    # --- 精确打补丁，解决冲突 ---
    ccxt.Exchange.__init__ = patch_factory(ccxt.Exchange.__init__, "sync")
    ccxt_async.Exchange.__init__ = patch_factory(ccxt_async.Exchange.__init__, "async")
    ccxt_pro.Exchange.__init__ = patch_factory(ccxt_pro.Exchange.__init__, "pro")

    print("🚀 CCXT 智能代理补丁已加载，同时支持同步和异步的REST API 和 WebSocket")
