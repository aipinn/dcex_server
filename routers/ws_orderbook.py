# routers/ws_orderbook.py
import asyncio
import json
from typing import Dict
from fastapi import WebSocket, WebSocketDisconnect
import ccxt.pro as ccxt_pro
import logging

logger = logging.getLogger(__name__)

# ----------------------- 配置常量（全局可调） -----------------------
SUBSCRIBE_DEPTH = 50  # 向交易所订阅的深度（top N levels），建议 50~500，根据交易所支持
CLIENT_DEPTH = 20  # 最终推送给客户端的最新档位数（首页推荐 10~30）
PUSH_INTERVAL = 1.0  # 推送间隔（秒），全量快照推送频率，0.2~1.0 之间平衡延迟与流量

# 缓存：{exchange:market_type:symbol → orderbook dict}
orderbook_cache: Dict[str, dict] = {}


async def watch_orderbook_task(
    ex: ccxt_pro.Exchange,
    symbol: str,
    market_type: str,
    websocket: WebSocket,
    exchange_id: str,
):
    """单个 symbol 的 orderbook 监听任务"""
    cache_key = f"{exchange_id}:{market_type}:{symbol}"

    while True:
        try:
            # 这里会读取当前的 ex.options["defaultType"]
            ob = await ex.watch_order_book(symbol, limit=SUBSCRIBE_DEPTH)

            # 只保留最新的 CLIENT_DEPTH 档
            processed_ob = {
                "bids": ob["bids"][:CLIENT_DEPTH] if ob.get("bids") else [],
                "asks": ob["asks"][:CLIENT_DEPTH] if ob.get("asks") else [],
                "timestamp": ob.get("timestamp"),
                "datetime": ob.get("datetime"),
                "nonce": ob.get("nonce") or 0,
            }

            # 更新缓存
            orderbook_cache[cache_key] = processed_ob

            # 统一响应结构 - orderbook_update
            await websocket.send_json(
                {
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "action": "orderbook_update",
                        "exchange": exchange_id,
                        "marketType": market_type,
                        "symbol": symbol,
                        "bids": processed_ob["bids"],
                        "asks": processed_ob["asks"],
                        "timestamp": processed_ob["timestamp"],
                        "datetime": processed_ob["datetime"],
                        "nonce": processed_ob["nonce"],
                    },
                    "ts": ex.milliseconds(),
                    "type": "ticker",
                }
            )

            # 控制推送频率
            await asyncio.sleep(PUSH_INTERVAL)

        except asyncio.CancelledError:
            logger.info(f"Orderbook task cancelled for {symbol} ({market_type})")
            break
        except Exception as e:
            logger.error(f"watch_orderbook {symbol} ({market_type}) 异常: {e}")
            # 可选：推送错误信息（统一结构）
            try:
                await websocket.send_json(
                    {
                        "code": 5001,
                        "msg": f"Orderbook fetch failed: {str(e)}",
                        "data": None,
                        "ts": ex.milliseconds(),
                    }
                )
            except:
                pass
            await asyncio.sleep(3)  # 短延迟重试，避免频繁报错


async def websocket_orderbook(websocket: WebSocket, exchange: str = "binance"):
    """
    WebSocket 端点：/api/ws/orderbook?exchange=binance
    客户端通过 JSON 消息订阅：
    {"action": "subscribe", "symbol": "BTC/USDT:USDT", "marketType": "swap"}
    {"action": "unsubscribe", "symbol": "BTC/USDT:USDT"}
    """
    await websocket.accept()
    logger.info(f"New orderbook WS connection: {exchange}")

    try:
        # 获取 ccxt.pro 实例（已打过代理补丁）
        ex = getattr(ccxt_pro, exchange)(
            {
                "enableRateLimit": True,
                "options": {
                    "defaultType": "spot",  # 初始默认 spot
                },
            }
        )

        # 该连接下的所有监听任务 {task_key: task}
        active_tasks: Dict[str, asyncio.Task] = {}

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                action = msg.get("action")
                symbol = msg.get("symbol", "").strip()
                market_type = msg.get("marketType", "spot").lower()

                if not symbol:
                    await websocket.send_json(
                        {
                            "code": 4001,
                            "msg": "symbol is required",
                            "data": None,
                            "ts": ex.milliseconds(),
                        }
                    )
                    continue

                # 动态设置 market type（核心逻辑不变）
                ex.options["defaultType"] = market_type

                if action == "subscribe":
                    task_key = f"{market_type}:{symbol}"  # 防止同 symbol 不同 type 冲突
                    if task_key not in active_tasks:
                        task = asyncio.create_task(
                            watch_orderbook_task(
                                ex, symbol, market_type, websocket, exchange
                            )
                        )
                        active_tasks[task_key] = task
                        logger.info(
                            f"✅ Subscribed orderbook: {symbol} ({market_type})"
                        )

                        # 统一响应结构 - subscribed
                        await websocket.send_json(
                            {
                                "code": 0,
                                "msg": "success",
                                "data": {
                                    "action": "subscribed",
                                    "symbol": symbol,
                                    "marketType": market_type,
                                },
                                "ts": ex.milliseconds(),
                            }
                        )

                elif action == "unsubscribe":
                    task_key = f"{market_type}:{symbol}"
                    task = active_tasks.pop(task_key, None)
                    if task:
                        task.cancel()
                        logger.info(
                            f"❌ Unsubscribed orderbook: {symbol} ({market_type})"
                        )

                        # 统一响应结构 - unsubscribed
                        await websocket.send_json(
                            {
                                "code": 0,
                                "msg": "success",
                                "data": {
                                    "action": "unsubscribed",
                                    "symbol": symbol,
                                    "marketType": market_type,
                                },
                                "ts": ex.milliseconds(),
                            }
                        )

                elif action == "ping":
                    # 统一响应结构 - pong
                    await websocket.send_json(
                        {
                            "code": 0,
                            "msg": "success",
                            "data": {"action": "pong"},
                            "ts": ex.milliseconds(),
                        }
                    )

                else:
                    await websocket.send_json(
                        {
                            "code": 4002,
                            "msg": f"Unknown action: {action}",
                            "data": None,
                            "ts": ex.milliseconds(),
                        }
                    )

            except json.JSONDecodeError:
                await websocket.send_json(
                    {
                        "code": 4003,
                        "msg": "Invalid JSON",
                        "data": None,
                        "ts": ex.milliseconds(),
                    }
                )
            except Exception as e:
                logger.error(f"Message processing error: {e}")
                await websocket.send_json(
                    {"code": 5000, "msg": str(e), "data": None, "ts": ex.milliseconds()}
                )

    except WebSocketDisconnect:
        logger.info("Orderbook WS closed by client")
    except Exception as e:
        logger.error(f"Orderbook WS global error: {e}")
        try:
            await websocket.send_json(
                {"code": 5000, "msg": str(e), "data": None, "ts": ex.milliseconds()}
            )
        except:
            pass
    finally:
        # 清理所有任务
        for task in active_tasks.values():
            task.cancel()
        active_tasks.clear()
        logger.info(f"Cleaned up {len(active_tasks)} orderbook tasks")
