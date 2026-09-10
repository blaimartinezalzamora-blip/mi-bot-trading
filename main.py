import os
import ccxt
import pandas as pd
from supabase import create_client

# Configuración de Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

# Cliente PÚBLICO para lectura de mercado (sin credenciales y sin carga de mercados previa)
exchange_publico = ccxt.binance({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
        'adjustForTimeDifference': True,
        'warnOnFetchOpenOrdersWithoutSymbol': False,
    }
})
exchange_publico.has['fetchMarkets'] = False

# Cliente PRIVADO solo para ejecución en Testnet
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

ACTIVOS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
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

def analizar_mercado(simbolo):
    try:
        # Petición directa de velas sin pasar por exchangeInfo
        ohlcv = exchange_publico.fetch_ohlcv(simbolo, timeframe='1h', limit=50)
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
