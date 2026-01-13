import asyncio
import json
import logging
import ccxt.pro as ccxt_pro
from fastapi import WebSocket, WebSocketDisconnect, Query
from typing import Dict, Any

logger = logging.getLogger(__name__)

def to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None

def to_int(v):
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        try:
            return int(float(v))
        except ValueError:
            return None
    return None

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
                    "markPrice": to_float(
                        ticker_raw.get("markPrice") or ticker_raw.get("info", {}).get("markPrice")
                    ),
                    "indexPrice": to_float(
                        ticker_raw.get("indexPrice") or ticker_raw.get("info", {}).get("indexPrice")
                    ),
                    "fundingRate": to_float(
                        ticker_raw.get("fundingRate") or ticker_raw.get("info", {}).get("fundingRate")
                    ),
                    "nextFundingTime": to_int(
                        ticker_raw.get("nextFundingTime") or ticker_raw.get("info", {}).get("nextFundingTime")
                    ),
                    "openInterest": to_float(
                        ticker_raw.get("openInterest") or ticker_raw.get("info", {}).get("openInterest")
                    ),
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
                logger.pretty(f"📤 {symbol} ({market_type}) 更新推送: {current_payload }")
            # else:
            #     logger.debug(f"⏳ {symbol} 变化太小，跳过推送")
                
    except asyncio.CancelledError:
        logger.info(f"🛑 {symbol} ({market_type}) 监听任务已取消")
    except Exception as e:
        logger.error(f"⚠️ {symbol} ({market_type}) 监听异常: {e}")
        await asyncio.sleep(5)  # 重试间隔

async def websocket_ticker(
    websocket: WebSocket,
    exchange: str = "binance"
):
    await websocket.accept()
    logger.info(f"New WS connection: {exchange}")
    
    try:
        ex = await get_exchange_pro(exchange)
        
        # 该连接下的所有监听任务 {symbol: task}
        active_tasks: Dict[str, asyncio.Task] = {}
        
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")
            symbol = msg.get("symbol", "").upper().strip()
            market_type = msg.get("marketType", "spot").lower()
            # market_type = 'future'
            if market_type != "spot":
                # 为每个 marketType 创建/缓存单独实例
                # perpetual / swap / future / option 等
                # ex = await get_exchange_pro(f"{exchange}_{market_type}")
                ex.options["defaultType"] = market_type

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
                        "symbol": symbol,
                        "marketType": market_type
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




# 并发多个监听
async def watch_ticker_task_pro(
    exchange: ccxt_pro.Exchange,
    symbol: str,
    market_type: str,
    websocket: WebSocket
):
    """真正的 WebSocket 推送任务，同时监听 ticker + markPrice（合约专用）"""
    logger.info(f"🚀 开始监听 {symbol} ({market_type}) WebSocket...")
    last_sent_data = None

    # 合约类型才监听 markPrice（包含 fundingRate）
    is_contract = market_type in ["perpetual", "delivery", "swap", "future"]

    async def ticker_loop():
        while True:
            ticker = await exchange.watch_ticker(symbol)
            return {"type": "ticker", "data": ticker}  # 只返回一次用于初始化

    async def mark_price_loop():
        if not is_contract:
            return None
        while True:
            mark = await exchange.watch_mark_price(symbol)
            return {"type": "mark_price", "data": mark}

    # 合并两个 loop 的结果（用 asyncio.gather 并发等待）
    try:
        while True:
            # 并发等待下一个 ticker 或 mark_price 更新
            done, pending = await asyncio.wait(
                [ticker_loop(), mark_price_loop()] if is_contract else [ticker_loop()],
                return_when=asyncio.FIRST_COMPLETED
            )

            for task in done:
                result = task.result()
                if result:
                    # 合并到 current_payload
                    current_payload = {
                        "symbol": symbol,
                        "marketType": market_type,
                        "last": result["data"].get("last"),
                        "open": result["data"].get("open"),
                        "high": result["data"].get("high"),
                        "low": result["data"].get("low"),
                        "bid": result["data"].get("bid"),
                        "ask": result["data"].get("ask"),
                        "change": result["data"].get("change"),
                        "percentage": result["data"].get("percentage"),
                        "baseVolume": result["data"].get("baseVolume") or 0.0,
                        "quoteVolume": result["data"].get("quoteVolume") or 0.0,
                        "timestamp": result["data"].get("timestamp") or int(asyncio.get_event_loop().time() * 1000),
                        "vwap": result["data"].get("vwap"),
                        "info": result["data"].get("info", {}),
                    }

                    # 总是从 mark_price 补充（如果有）
                    if is_contract and result["type"] == "mark_price":
                        current_payload.update({
                            "markPrice": result["data"].get("markPrice"),
                            "indexPrice": result["data"].get("indexPrice"),
                            "fundingRate": result["data"].get("fundingRate"),  # ← 这里就是资金费率！
                            "nextFundingTime": result["data"].get("nextFundingTime"),
                            "openInterest": result["data"].get("openInterest"),
                        })

                    # Diff 检查 + 推送（逻辑不变）
                    should_send = False
                    if last_sent_data is None:
                        should_send = True
                    else:
                        old_comp = {
                            "last": last_sent_data.get("last"),
                            "percentage": last_sent_data.get("percentage"),
                            "fundingRate": last_sent_data.get("fundingRate"),
                        }
                        new_comp = {
                            "last": current_payload.get("last"),
                            "percentage": current_payload.get("percentage"),
                            "fundingRate": current_payload.get("fundingRate"),
                        }
                        if has_meaningful_change(old_comp, new_comp, pct_threshold=0.0005):  # fundingRate 阈值可调小
                            should_send = True

                    if should_send:
                        await websocket.send_text(json.dumps({
                            "type": "ticker_update",
                            "data": current_payload
                        }, ensure_ascii=False))
                        last_sent_data = current_payload.copy()
                        logger.info(f"📤 {symbol} ({market_type}) 更新推送: last={current_payload.get('last')}, fundingRate={current_payload.get('fundingRate')}")

                    # 取消已完成的 pending task，避免内存泄漏
                    for p in pending:
                        p.cancel()

    except asyncio.CancelledError:
        logger.info(f"🛑 {symbol} ({market_type}) 监听任务已取消")
    except Exception as e:
        logger.error(f"⚠️ {symbol} ({market_type}) 监听异常: {e}")
        await asyncio.sleep(5)
