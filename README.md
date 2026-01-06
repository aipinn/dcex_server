# Crypto Proxy API

A CCXT-based cryptocurrency exchange aggregation API, built with FastAPI and CCXT.

This project acts as a proxy API layer between frontend applications and multiple cryptocurrency exchanges, providing a unified and consistent API for market data access.

Status: Work in progress. This project is under active development and not feature-complete yet.

---

Overview

Backend Framework: FastAPI  
Exchange SDK: CCXT  
API Type: REST (WebSocket supported)  
Python Version: 3.9+

By abstracting exchange-specific APIs, clients can switch exchanges simply by changing the exchange parameter.

---

About CCXT

This project is built on top of CCXT, a widely used cryptocurrency trading library.

CCXT GitHub: https://github.com/ccxt/ccxt

CCXT provides:
- Unified exchange APIs
- Built-in rate limiting
- Normalized market data structures
- Support for hundreds of centralized and decentralized exchanges

This service exposes CCXT capabilities through a clean HTTP and WebSocket API for frontend consumption.

---

Core Features

Unified Exchange API
- Same request format for Binance, OKX, Bybit, etc.
- Switch exchanges using a single exchange query parameter

Automatic Rate Limiting
- Handled internally by CCXT
- Prevents exchange-side throttling and bans

Extensible Architecture
Planned and supported features:
- Market tickers
- OHLC / K-line data
- Order book depth
- Trade history
- Batch endpoints
- WebSocket streaming

Auto-generated API Documentation
- Swagger UI powered by FastAPI
- Interactive API testing in browser

---

Quick Start

Install dependencies:
pip install -r requirements.txt

Activate virtual environment:
source venv/bin/activate

Run development server:
uvicorn main:app --reload

Open API documentation:
http://127.0.0.1:8000/docs

---

WebSocket Support

Example WebSocket endpoint:
ws://localhost:8000/api/ws/ticker?exchange=binance

The backend manages exchange connections and forwards normalized real-time data to connected clients.

---

Frontend Integration

This project is designed to work with a Flutter-based client.

Frontend repository:
https://github.com/aipinn/dcex.git

---

Disclaimer

This project is for educational and research purposes only.
It is not a trading platform and does not provide financial advice.
Use at your own risk.

---

License

MIT License