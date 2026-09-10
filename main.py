import os
import requests
import pandas as pd
from supabase import create_client
import ccxt

# Configuración de Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

# Cliente PRIVADO solo para cuando haya que ejecutar órdenes en Testnet
def obtener_exchange_privado():
    exchange = ccxt.binance({
        'apiKey': os.environ.get("BINANCE_TESTNET_KEY", ""),
        'secret': os.environ.get("BINANCE_TESTNET_SECRET", ""),
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',
            'adjustForTimeDifference': True,
        }
    })
    exchange.set_sandbox_mode(True)
    return exchange

ACTIVOS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
RESERVA_SERVIDORES = 20.0

def obtener_capital_operable():
    if not supabase:
        return 0.0
    try:
        res = supabase.table('depositos').select('monto').execute()
        monto_total = sum(item['monto'] for item in res.data) if res.data else 0.0
        return max(0.0, monto_total - RESERVA_SERVIDORES)
    except Exception as e:
        print(f"Error al obtener capital desde Supabase: {e}")
        return 0.0

def obtener_velas_directas(simbolo):
    # Petición HTTP directa omitiendo librerías intermedias
    url = f"https://api.binance.com/api/v3/klines?symbol={simbolo}&interval=1h&limit=50"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    response = requests.get(url, headers=headers, timeout=10)
    
    if response.status_code == 451:
        # Si la IP del servidor sigue bloqueada por la API de Binance, usamos CoinGecko/Alternative API como respaldo
        return obtener_velas_respaldo(simbolo)
        
    response.raise_for_status()
    data = response.json()
    
    # Formatear datos a lista de precios de cierre
    ohlcv = []
    for item in data:
        ohlcv.append([
            item[0],           # timestamp
            float(item[1]),    # open
            float(item[2]),    # high
            float(item[3]),    # low
            float(item[4]),    # close
            float(item[5])     # volume
        ])
    return ohlcv

def obtener_velas_respaldo(simbolo):
    # Endpoint alternativo libre de geobloqueos
    coin_map = {'BTCUSDT': 'bitcoin', 'ETHUSDT': 'ethereum', 'SOLUSDT': 'solana'}
    coin_id = coin_map.get(simbolo, 'bitcoin')
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=2"
    res = requests.get(url, timeout=10)
    res.raise_for_status()
    prices = res.json().get('prices', [])
    
    # Adaptar estructura a DataFrame
    ohlcv = [[p[0], p[1], p[1], p[1], p[1], 0] for p in prices[-50:]]
    return ohlcv

def analizar_mercado(simbolo):
    try:
        ohlcv = obtener_velas_directas(simbolo)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Estrategia de análisis básica
        df['sma_short'] = df['close'].rolling(window=9).mean()
        df['sma_long'] = df['close'].rolling(window=21).mean()
        
        # Últimos valores
        ultima_corta = df['sma_short'].iloc[-1]
        ultima_larga = df['sma_long'].iloc[-1]
        penultima_corta = df['sma_short'].iloc[-2]
        penultima_larga = df['sma_long'].iloc[-2]
        
        # Cruce alcista
        if penultima_corta <= penultima_larga and ultima_corta > ultima_larga:
            return "BUY"
        return "HOLD"
    except Exception as e:
        print(f"Error analizando {simbolo}: {e}")
        return "ERROR"

def iniciar_bot():
    print("🤖 Bot de Trading Autosostenible Iniciado...")
    capital = obtener_capital_operable()
    print(f"💰 Capital operable: {capital:.2f} €")
    
    entradas_encontradas = 0
    for simbolo in ACTIVOS:
        senal = analizar_mercado(simbolo)
        if senal == "BUY":
            print(f"🚀 Señal de COMPRA detectada en {simbolo}")
            entradas_encontradas += 1
            
    if entradas_encontradas == 0:
        print("🔍 No se encontraron entradas de alta probabilidad.")

if __name__ == "__main__":
    iniciar_bot()
