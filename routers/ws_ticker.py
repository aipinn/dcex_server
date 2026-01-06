# from fastapi import WebSocket, WebSocketDisconnect, Query
# import ccxt
# import asyncio
# import json
# import logging

# logger = logging.getLogger(__name__)

# # =========================
# # Exchange 管理（全局缓存）
# # =========================
# exchanges: dict[str, ccxt.Exchange] = {}


# def get_exchange_sync(exchange_name: str) -> ccxt.Exchange:
#     exchange_name = exchange_name.lower().strip()
#     if exchange_name not in exchanges:
#         ex_class = getattr(ccxt, exchange_name, None)
#         if not ex_class:
#             raise ValueError(f"不支持的交易所: {exchange_name}")
#         ex = ex_class()
#         ex.load_markets()  # 同步调用
#         exchanges[exchange_name] = ex
#     return exchanges[exchange_name]


# # =========================
# # WS 推送 ticker
# # =========================
# async def send_ticker(websocket: WebSocket, symbol: str, ticker: dict):
#     try:
#         last = ticker.get("last")
#         percentage = ticker.get("percentage")
#         absolute = ticker.get("change")
#         data = {
#             "symbol": symbol,
#             "price": {
#                 "last": last,
#                 "high": ticker.get("high"),
#                 "low": ticker.get("low"),
#                 "change": {
#                     "percentage": percentage,
#                     "absolute": absolute,
#                 },
#             },
#             "volume": ticker.get("baseVolume") or ticker.get("volume"),
#             "volumeQuote": ticker.get("quoteVolume"),
#             "timestamp": ticker.get("timestamp")
#             or int(asyncio.get_event_loop().time() * 1000),
#         }
#         await websocket.send_text(json.dumps(data, ensure_ascii=False))
#     except WebSocketDisconnect:
#         raise
#     except Exception:
#         pass  # WS 已关闭或写失败，直接忽略


# def fetch_ticker_sync(exchange: ccxt.Exchange, symbol: str) -> dict:
#     return exchange.fetch_ticker(symbol)


# def has_meaningful_change(
#     old: dict, new: dict, price_threshold: float = 1e-8, pct_threshold: float = 0.01
# ) -> bool:
#     old_last = old.get("last")
#     new_last = new.get("last")
#     if old_last is not None and new_last is not None:
#         if old_last != 0 and abs(new_last - old_last) / abs(old_last) > price_threshold:
#             return True

#     old_pct = old.get("percentage")
#     new_pct = new.get("percentage")
#     if old_pct is not None and new_pct is not None:
#         if abs(new_pct - old_pct) > pct_threshold:
#             return True

#     return False


# async def watch_single_ticker(
#     exchange: ccxt.Exchange,
#     symbol: str,
#     websocket: WebSocket,
# ):
#     """长期轮询任务：仅负责后续更新，使用 diff 控制避免重复推送"""
#     last_ticker: dict | None = None
#     try:
#         while True:
#             try:
#                 ticker = await asyncio.to_thread(fetch_ticker_sync, exchange, symbol)
#                 # 临时强制推送，用于排查 TRX/USDT 数据异常问题
#                 # await send_ticker(websocket, symbol, ticker)
#                 # last_ticker = ticker.copy()

#                 should_send = False
#                 if last_ticker is None:
#                     # 理论上不会走到这里（首次已由 initial 发送），但保留防御性逻辑
#                     should_send = True
#                 elif has_meaningful_change(last_ticker, ticker):
#                     should_send = True

#                 if should_send:
#                     await send_ticker(websocket, symbol, ticker)
#                     last_ticker = ticker.copy()

#             except Exception as e:
#                 logger.error(f"watch_ticker {symbol} error: {e}")

#             await asyncio.sleep(3)

#     except asyncio.CancelledError:
#         return
#     except WebSocketDisconnect:
#         return
#     except Exception as e:
#         logger.error(f"watch_single_ticker unexpected error {symbol}: {e}")


# # =========================
# # WebSocket 接口
# # =========================
# async def websocket_ticker(
#     websocket: WebSocket,
#     exchange: str = Query("binance"),
# ):
#     exchange = exchange.lower().strip()
#     await websocket.accept()
#     logger.info(f"WebSocket connected - exchange: {exchange}")

#     watch_task: asyncio.Task | None = None
#     ex: ccxt.Exchange | None = None

#     try:
#         ex = await asyncio.to_thread(get_exchange_sync, exchange)

#         while True:
#             raw = await websocket.receive_text()
#             try:
#                 msg = json.loads(raw)
#             except json.JSONDecodeError:
#                 continue

#             action = msg.get("action")

#             if action == "subscribe":
#                 symbol = msg.get("symbol")
#                 if not isinstance(symbol, str):
#                     continue
#                 symbol = symbol.upper().strip()

#                 # 取消旧任务
#                 if watch_task and not watch_task.done():
#                     watch_task.cancel()
#                     try:
#                         await watch_task
#                     except asyncio.CancelledError:
#                         pass
#                 watch_task = None

#                 # 发送订阅确认
#                 await websocket.send_text(
#                     json.dumps({"action": "subscribe", "symbol": symbol})
#                 )

#                 # 【关键】订阅成功后立即推送一次最新 ticker（带重试）
#                 async def send_initial_ticker():
#                     max_attempts = 5
#                     for attempt in range(max_attempts):
#                         try:
#                             ticker = await asyncio.to_thread(
#                                 fetch_ticker_sync, ex, symbol
#                             )
#                             await send_ticker(websocket, symbol, ticker)
#                             logger.info(f"Initial ticker sent for {symbol}")
#                             return
#                         except Exception as e:
#                             logger.warning(
#                                 f"Initial ticker fetch failed (attempt {attempt + 1}/{max_attempts}): {e}"
#                             )
#                             if attempt < max_attempts - 1:
#                                 await asyncio.sleep(1)  # 指数退避可选，这里简单 1s

#                     # 所有重试都失败，发送错误提示（可选）
#                     try:
#                         await websocket.send_text(
#                             json.dumps(
#                                 {
#                                     "action": "error",
#                                     "symbol": symbol,
#                                     "message": "Failed to fetch initial ticker after retries",
#                                 }
#                             )
#                         )
#                     except:
#                         pass

#                 asyncio.create_task(send_initial_ticker())

#                 # 启动长期轮询任务（diff 控制后续更新）
#                 watch_task = asyncio.create_task(
#                     watch_single_ticker(ex, symbol, websocket)
#                 )

#             elif action == "unsubscribe":
#                 if watch_task and not watch_task.done():
#                     watch_task.cancel()
#                     try:
#                         await watch_task
#                     except asyncio.CancelledError:
#                         pass
#                 watch_task = None
#                 await websocket.send_text(json.dumps({"action": "unsubscribed"}))

#             elif action == "ping":
#                 await websocket.send_text(json.dumps({"action": "pong"}))

#     except WebSocketDisconnect:
#         logger.info("WebSocket disconnected")
#     except Exception as e:
#         logger.error(f"WebSocket error: {e}")
#     finally:
#         if watch_task and not watch_task.done():
#             watch_task.cancel()
#             try:
#                 await watch_task
#             except asyncio.CancelledError:
#                 pass

#         try:
#             await websocket.close()
#         except Exception:
#             pass


# import asyncio
# import json
# import logging
# import ccxt.pro as ccxt_pro  # 必须使用 pro
# from fastapi import WebSocket, WebSocketDisconnect, Query

# logger = logging.getLogger(__name__)

# # =========================
# # Exchange 管理（Pro 全局缓存）
# # =========================
# exchanges: dict[str, ccxt_pro.Exchange] = {}


# async def get_exchange_pro(exchange_name: str) -> ccxt_pro.Exchange:
#     exchange_name = exchange_name.lower().strip()
#     if exchange_name not in exchanges:
#         ex_class = getattr(ccxt_pro, exchange_name, None)
#         if not ex_class:
#             raise ValueError(f"不支持的交易所: {exchange_name}")

#         # 使用你之前调试成功的方案 B/C 配置代理
#         ex = ex_class()
#         exchanges[exchange_name] = ex
#     return exchanges[exchange_name]


# # =========================
# # 真正的 WebSocket 监听任务
# # =========================
# async def watch_ticker_task(
#     exchange: ccxt_pro.Exchange,
#     symbol: str,
#     websocket: WebSocket,
# ):
#     """
#     使用 ccxt.pro 的 watch_ticker。
#     当交易所推送新数据时，该方法才会返回，否则一直挂起等待。
#     """
#     logger.info(f"🚀 [WS监听启动] 目标: {symbol}")
#     print(f"\n[DEBUG] 任务启动：正在准备连接 {symbol} 的 WebSocket...")
#     try:
#         while True:
#             # 加上超时检测，如果 10 秒没收到数据，主动报错
#             logger.debug(f"正在等待 {symbol} 的数据推送...")
#             # 💡 核心改动：不再 sleep，而是 watch
#             ticker = await exchange.watch_ticker(symbol)

#             # 构建推送数据
#             data = {
#                 "symbol": symbol,
#                 "price": {
#                     "last": ticker.get("last"),
#                     "high": ticker.get("high"),
#                     "low": ticker.get("low"),
#                     "change": {
#                         "percentage": ticker.get("percentage"),
#                         "absolute": ticker.get("change"),
#                     },
#                 },
#                 "volume": ticker.get("baseVolume") or ticker.get("volume"),
#                 "volumeQuote": ticker.get("quoteVolume"),
#                 "timestamp": ticker.get("timestamp")
#                 or int(asyncio.get_event_loop().time() * 1000),
#             }
#             logger.info(f"✅ [收到数据] {symbol}: {ticker['last']}")
#             await websocket.send_text(json.dumps(data, ensure_ascii=False))

#     except asyncio.CancelledError:
#         logger.info(f"Task cancelled for {symbol}")
#     except Exception as e:
#         logger.error(f"watch_ticker error for {symbol}: {e}")
#         # 如果断开，等待几秒后通常外层循环或机制会处理重连
#         await asyncio.sleep(5)


# # =========================
# # WebSocket 接口
# # =========================
# async def websocket_ticker(
#     websocket: WebSocket,
#     exchange_name: str = Query("binance"),
# ):
#     await websocket.accept()
#     ex = await get_exchange_pro(exchange_name)

#     # 跟踪当前活跃的 watch 任务
#     active_tasks: dict[str, asyncio.Task] = {}

#     try:
#         while True:
#             raw = await websocket.receive_text()
#             msg = json.loads(raw)
#             action = msg.get("action")
#             symbol = msg.get("symbol", "").upper().strip()
#             if action == "subscribe" and symbol:
#                 # 1. 取消旧任务（如果你的业务逻辑是每个连接只看一个币）
#                 for t in active_tasks.values():
#                     t.cancel()
#                 active_tasks.clear()

#                 # 2. 启动真正的 WS 监听任务
#                 task = asyncio.create_task(watch_ticker_task(ex, symbol, websocket))
#                 active_tasks[symbol] = task

#                 await websocket.send_text(
#                     json.dumps({"action": "subscribe", "symbol": symbol})
#                 )

#             elif action == "unsubscribe":
#                 for t in active_tasks.values():
#                     t.cancel()
#                 active_tasks.clear()
#                 await websocket.send_text(json.dumps({"action": "unsubscribed"}))

#             elif action == "ping":
#                 await websocket.send_text(json.dumps({"action": "pong"}))

#     except WebSocketDisconnect:
#         logger.info("Client disconnected")
#     finally:
#         # 清理所有任务
#         for t in active_tasks.values():
#             t.cancel()
#         # ⚠️ 注意：不要在这里 ex.close()，因为 ex 是全局共享的


import asyncio
import json
import logging
import ccxt.pro as ccxt_pro
from fastapi import WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger(__name__)

# 全局交易所缓存 (CCXT Pro 实例)
exchanges: dict[str, ccxt_pro.Exchange] = {}


async def get_exchange_pro(exchange_name: str) -> ccxt_pro.Exchange:
    exchange_name = exchange_name.lower().strip()
    if exchange_name not in exchanges:
        ex_class = getattr(ccxt_pro, exchange_name, None)
        if not ex_class:
            raise ValueError(f"不支持的交易所: {exchange_name}")
        # 实例化时补丁会自动注入代理
        exchanges[exchange_name] = ex_class()
    return exchanges[exchange_name]


def has_meaningful_change(
    old: dict, new: dict, price_threshold: float = 1e-8, pct_threshold: float = 0.01
) -> bool:
    """对比价格和涨跌幅是否有意义的变动"""
    old_last = old.get("last")
    new_last = new.get("last")
    if old_last and new_last and old_last != 0:
        if abs(new_last - old_last) / abs(old_last) > price_threshold:
            return True

    old_pct = old.get("percentage")
    new_pct = new.get("percentage")
    if old_pct is not None and new_pct is not None:
        if abs(new_pct - old_pct) > pct_threshold:
            return True
    return False


async def watch_ticker_task(
    exchange: ccxt_pro.Exchange, symbol: str, websocket: WebSocket
):
    """真正的 WebSocket 推送任务，带首次推送和 Diff 过滤"""
    logger.info(f"🚀 开始监听 {symbol} WebSocket...")
    last_sent_data = None

    try:
        while True:
            # 1. 挂起等待交易所推送 (非轮询)
            ticker = await exchange.watch_ticker(symbol)

            # 2. 格式化数据包
            current_payload = {
                "symbol": symbol,
                "price": {
                    "last": ticker.get("last"),
                    "high": ticker.get("high"),
                    "low": ticker.get("low"),
                    "change": {
                        "percentage": ticker.get("percentage"),
                        "absolute": ticker.get("change"),
                    },
                },
                "volume": ticker.get("baseVolume") or ticker.get("volume"),
                "volumeQuote": ticker.get("quoteVolume"),
                "timestamp": ticker.get("timestamp")
                or int(asyncio.get_event_loop().time() * 1000),
            }

            # 3. 首次推送或 Diff 检查
            should_send = False
            if last_sent_data is None:
                should_send = True  # 首次订阅强制推送
            else:
                # 提取关键字段进行对比
                old_comp = {
                    "last": last_sent_data["price"]["last"],
                    "percentage": last_sent_data["price"]["change"]["percentage"],
                }
                new_comp = {
                    "last": current_payload["price"]["last"],
                    "percentage": current_payload["price"]["change"]["percentage"],
                }
                if has_meaningful_change(old_comp, new_comp):
                    should_send = True

            # 4. 执行推送
            if should_send:
                await websocket.send_text(
                    json.dumps(
                        {"type": "ticker", "data": current_payload}, ensure_ascii=False
                    )
                )
                last_sent_data = current_payload.copy()
                # logger.info(f"📊 {symbol} 价格更新: {current_payload['price']['last']}")
            else:
                pass
                # logger.info(f"⏰ {symbol} 变化不大，不需要推送 ")

    except asyncio.CancelledError:
        logger.info(f"🛑 {symbol} 监听任务已取消")
    except Exception as e:
        logger.error(f"⚠️ {symbol} 监听异常: {e}")
        await asyncio.sleep(5)  # 出错后等待重试


async def websocket_ticker(websocket: WebSocket, exchange_name: str = Query("binance")):
    await websocket.accept()
    logger.info(f"New connection established for {exchange_name}")

    ex = await get_exchange_pro(exchange_name)
    # 存储该链接下所有的监听任务 {symbol: task}
    active_tasks: dict[str, asyncio.Task] = {}

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")
            symbol = msg.get("symbol", "").upper().strip()

            if action == "subscribe" and symbol:
                # 💡 改进点：如果已经订阅过，就不重复启动任务
                if symbol not in active_tasks:
                    task = asyncio.create_task(watch_ticker_task(ex, symbol, websocket))
                    active_tasks[symbol] = task
                    logger.info(f"✅ Added subscription: {symbol}")
                    logger.info(
                        f"🍃 Subscribed symbols ({len(active_tasks)}): {list(active_tasks.keys())}"
                    )

                await websocket.send_text(
                    json.dumps({"action": "subscribed", "symbol": symbol})
                )

            elif action == "unsubscribe" and symbol:
                # 💡 改进点：精准取消某一个币种的监听
                task = active_tasks.pop(symbol, None)
                if task:
                    task.cancel()
                    logger.info(f"❌ Removed subscription: {symbol}")
                    logger.info(
                        f"💀 Subscribed symbols ({len(active_tasks)}): {list(active_tasks.keys())}"
                    )
                await websocket.send_text(
                    json.dumps({"action": "unsubscribed", "symbol": symbol})
                )

            elif action == "ping":
                await websocket.send_text(json.dumps({"action": "pong"}))

    except WebSocketDisconnect:
        logger.info("Connection closed by client")
    finally:
        # 链接断开时，清理该用户所有的监听任务
        for t in active_tasks.values():
            t.cancel()
        active_tasks.clear()