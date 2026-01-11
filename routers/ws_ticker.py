# import asyncio
# import json
# import logging
# import ccxt.pro as ccxt_pro
# from fastapi import WebSocket, WebSocketDisconnect, Query

# logger = logging.getLogger(__name__)

# # 全局交易所缓存 (CCXT Pro 实例)
# exchanges: dict[str, ccxt_pro.Exchange] = {}


# async def get_exchange_pro(exchange_name: str) -> ccxt_pro.Exchange:
#     exchange_name = exchange_name.lower().strip()
#     if exchange_name not in exchanges:
#         ex_class = getattr(ccxt_pro, exchange_name, None)
#         if not ex_class:
#             raise ValueError(f"不支持的交易所: {exchange_name}")
#         # 实例化时补丁会自动注入代理
#         exchanges[exchange_name] = ex_class()
#     return exchanges[exchange_name]


# def has_meaningful_change(
#     old: dict, new: dict, price_threshold: float = 1e-8, pct_threshold: float = 0.01
# ) -> bool:
#     """对比价格和涨跌幅是否有意义的变动"""
#     old_last = old.get("last")
#     new_last = new.get("last")
#     if old_last and new_last and old_last != 0:
#         if abs(new_last - old_last) / abs(old_last) > price_threshold:
#             return True

#     old_pct = old.get("percentage")
#     new_pct = new.get("percentage")
#     if old_pct is not None and new_pct is not None:
#         if abs(new_pct - old_pct) > pct_threshold:
#             return True
#     return False


# async def watch_ticker_task(
#     exchange: ccxt_pro.Exchange, symbol: str, websocket: WebSocket
# ):
#     """真正的 WebSocket 推送任务，带首次推送和 Diff 过滤"""
#     logger.info(f"🚀 开始监听 {symbol} WebSocket...")
#     last_sent_data = None

#     try:
#         while True:
#             # 1. 挂起等待交易所推送 (非轮询)
#             ticker = await exchange.watch_ticker(symbol)
#             logger.info(
#                 "🌞 ticker:\n%s",
#                 json.dumps(ticker, indent=2, ensure_ascii=False)
#             )            
#             # 2. 格式化数据包
#             current_payload = {
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

#             # 3. 首次推送或 Diff 检查
#             should_send = False
#             if last_sent_data is None:
#                 should_send = True  # 首次订阅强制推送
#             else:
#                 # 提取关键字段进行对比
#                 old_comp = {
#                     "last": last_sent_data["price"]["last"],
#                     "percentage": last_sent_data["price"]["change"]["percentage"],
#                 }
#                 new_comp = {
#                     "last": current_payload["price"]["last"],
#                     "percentage": current_payload["price"]["change"]["percentage"],
#                 }
#                 if has_meaningful_change(old_comp, new_comp):
#                     should_send = True

#             # 4. 执行推送
#             if should_send:
#                 await websocket.send_text(
#                     json.dumps(
#                         {"type": "ticker", "data": current_payload}, ensure_ascii=False
#                     )
#                 )
#                 last_sent_data = current_payload.copy()
#                 # logger.info(f"📊 {symbol} 价格更新: {current_payload['price']['last']}")
#             else:
#                 pass
#                 # logger.info(f"⏰ {symbol} 变化不大，不需要推送 ")

#     except asyncio.CancelledError:
#         logger.info(f"🛑 {symbol} 监听任务已取消")
#     except Exception as e:
#         logger.error(f"⚠️ {symbol} 监听异常: {e}")
#         await asyncio.sleep(5)  # 出错后等待重试


# async def websocket_ticker(websocket: WebSocket, exchange_name: str = Query("binance")):
#     await websocket.accept()
#     logger.info(f"New connection established for {exchange_name}")

#     ex = await get_exchange_pro(exchange_name)
#     # 存储该链接下所有的监听任务 {symbol: task}
#     active_tasks: dict[str, asyncio.Task] = {}

#     try:
#         while True:
#             raw = await websocket.receive_text()
#             msg = json.loads(raw)
#             action = msg.get("action")
#             symbol = msg.get("symbol", "").upper().strip()

#             if action == "subscribe" and symbol:
#                 # 💡 改进点：如果已经订阅过，就不重复启动任务
#                 if symbol not in active_tasks:
#                     task = asyncio.create_task(watch_ticker_task(ex, symbol, websocket))
#                     active_tasks[symbol] = task
#                     logger.info(f"✅ Added subscription: {symbol}")
#                     logger.info(
#                         f"🍃 Subscribed symbols ({len(active_tasks)}): {list(active_tasks.keys())}"
#                     )

#                 await websocket.send_text(
#                     json.dumps({"action": "subscribed", "symbol": symbol})
#                 )

#             elif action == "unsubscribe" and symbol:
#                 # 💡 改进点：精准取消某一个币种的监听
#                 task = active_tasks.pop(symbol, None)
#                 if task:
#                     task.cancel()
#                     logger.info(f"❌ Removed subscription: {symbol}")
#                     logger.info(
#                         f"💀 Subscribed symbols ({len(active_tasks)}): {list(active_tasks.keys())}"
#                     )
#                 await websocket.send_text(
#                     json.dumps({"action": "unsubscribed", "symbol": symbol})
#                 )

#             elif action == "ping":
#                 await websocket.send_text(json.dumps({"action": "pong"}))

#     except WebSocketDisconnect:
#         logger.info("Connection closed by client")
#     finally:
#         # 链接断开时，清理该用户所有的监听任务
#         for t in active_tasks.values():
#             t.cancel()
#         active_tasks.clear()


import asyncio
import json
import logging
import ccxt.pro as ccxt_pro
from fastapi import WebSocket, WebSocketDisconnect, Query
from typing import Dict, Any

logger = logging.getLogger(__name__)

# 全局交易所缓存 (ccxt.pro 实例)
exchanges: Dict[str, ccxt_pro.Exchange] = {}

async def get_exchange_pro(exchange_name: str) -> ccxt_pro.Exchange:
    exchange_name = exchange_name.lower().strip()
    if exchange_name not in exchanges:
        ex_class = getattr(ccxt_pro, exchange_name, None)
        if not ex_class:
            raise ValueError(f"不支持的交易所: {exchange_name}")
        # 实例化时补丁会自动注入代理和 defaultType
        exchanges[exchange_name] = ex_class()
    return exchanges[exchange_name]

def has_meaningful_change(old: Dict, new: Dict, price_threshold: float = 1e-8, pct_threshold: float = 0.01) -> bool:
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
    exchange: ccxt_pro.Exchange,
    symbol: str,
    market_type: str,
    websocket: WebSocket
):
    """真正的 WebSocket 推送任务，支持多市场类型，带首次推送和 Diff 过滤"""
    logger.info(f"🚀 开始监听 {symbol} ({market_type}) WebSocket...")
    last_sent_data = None
    
    try:
        while True:
            # 1. 等待交易所真实推送（ccxt.pro watch_ticker 是异步阻塞式）
            ticker_raw = await exchange.watch_ticker(symbol)
            
            # 2. 统一构建推送数据结构（兼容你的 freezed TickerModel）
            current_payload: Dict[str, Any] = {
                "symbol": symbol,
                "marketType": market_type,
                "last": ticker_raw.get("last"),
                "open": ticker_raw.get("open"),
                "high": ticker_raw.get("high"),
                "low": ticker_raw.get("low"),
                "bid": ticker_raw.get("bid"),
                "ask": ticker_raw.get("ask"),
                "change": ticker_raw.get("change"),
                "percentage": ticker_raw.get("percentage"),
                "baseVolume": ticker_raw.get("baseVolume") or 0.0,
                "quoteVolume": ticker_raw.get("quoteVolume") or 0.0,
                "timestamp": ticker_raw.get("timestamp") or int(asyncio.get_event_loop().time() * 1000),
                "vwap": ticker_raw.get("vwap"),
                "info": ticker_raw.get("info", {}),
            }
            
            # 补充市场类型专有字段
            if market_type in ["perpetual", "delivery", "swap", "future"]:
                current_payload.update({
                    "markPrice": ticker_raw.get("markPrice"),
                    "indexPrice": ticker_raw.get("indexPrice"),
                    "fundingRate": ticker_raw.get("fundingRate"),
                    "nextFundingTime": ticker_raw.get("nextFundingTime"),
                    "openInterest": ticker_raw.get("openInterest"),
                })
            
            elif market_type == "option":
                current_payload.update({
                    "strikePrice": ticker_raw.get("strike"),
                    "expiryDate": ticker_raw.get("expiry"),
                    "optionType": "call" if "C" in symbol.upper() else "put",
                    "impliedVolatility": ticker_raw.get("impliedVolatility"),
                    "underlyingPrice": ticker_raw.get("underlyingPrice"),
                })
            
            # 3. Diff 检查：首次强制推送，否则只推送有意义变化
            should_send = False
            if last_sent_data is None:
                should_send = True
            else:
                old_comp = {
                    "last": last_sent_data.get("last"),
                    "percentage": last_sent_data.get("percentage"),
                }
                new_comp = {
                    "last": current_payload.get("last"),
                    "percentage": current_payload.get("percentage"),
                }
                if has_meaningful_change(old_comp, new_comp):
                    should_send = True
            
            # 4. 推送
            if should_send:
                await websocket.send_text(json.dumps({
                    "type": "ticker",
                    "data": current_payload
                }, ensure_ascii=False))
                
                last_sent_data = current_payload.copy()
                logger.info(f"📤 {symbol} ({market_type}) 更新推送: {current_payload['last']}")
            # else:
            #     logger.debug(f"⏳ {symbol} 变化太小，跳过推送")
                
    except asyncio.CancelledError:
        logger.info(f"🛑 {symbol} ({market_type}) 监听任务已取消")
    except Exception as e:
        logger.error(f"⚠️ {symbol} ({market_type}) 监听异常: {e}")
        await asyncio.sleep(5)  # 重试间隔

async def websocket_ticker(
    websocket: WebSocket,
    exchange: str = "binance",
    market_type: str = "spot"
):
    await websocket.accept()
    logger.info(f"New WS connection: {exchange} | market_type: {market_type}")
    
    try:
        ex = await get_exchange_pro(exchange)
        
        # 设置交易所的 defaultType（ccxt.pro 支持）
        if market_type != "spot":
            ex.options["defaultType"] = market_type  # perpetual / swap / future / option 等
        
        # 该连接下的所有监听任务 {symbol: task}
        active_tasks: Dict[str, asyncio.Task] = {}
        
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")
            symbol = msg.get("symbol", "").upper().strip()
            
            if action == "subscribe" and symbol:
                if symbol not in active_tasks:
                    task = asyncio.create_task(
                        watch_ticker_task(ex, symbol, market_type, websocket)
                    )
                    active_tasks[symbol] = task
                    logger.info(f"✅ Subscribed: {symbol} ({market_type})")
                    await websocket.send_text(json.dumps({
                        "action": "subscribed",
                        "symbol": symbol,
                        "marketType": market_type
                    }))
            
            elif action == "unsubscribe" and symbol:
                task = active_tasks.pop(symbol, None)
                if task:
                    task.cancel()
                    logger.info(f"❌ Unsubscribed: {symbol} ({market_type})")
                    await websocket.send_text(json.dumps({
                        "action": "unsubscribed",
                        "symbol": symbol
                    }))
            
            elif action == "ping":
                await websocket.send_text(json.dumps({"action": "pong"}))
    
    except WebSocketDisconnect:
        logger.info("WS connection closed by client")
    
    except Exception as e:
        logger.error(f"WS 全局异常: {e}")
        await websocket.send_text(json.dumps({"error": str(e)}))
    
    finally:
        # 清理所有任务
        for task in active_tasks.values():
            task.cancel()
        active_tasks.clear()
        logger.info(f"Cleaned up {len(active_tasks)} tasks for closed connection")