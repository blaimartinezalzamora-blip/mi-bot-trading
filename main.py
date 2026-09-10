import os
import requests
import pandas as pd
from supabase import create_client
import ccxt

# Configuración de Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

# Cliente PRIVADO para ejecución en Binance Testnet
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
PORCENTAJE_POR_OPERACION = 0.10  # Usa el 10% del capital operable por señal

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
    url = f"https://api.binance.com/api/v3/klines?symbol={simbolo}&interval=1h&limit=50"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers, timeout=10)
    
    if response.status_code == 451:
        return obtener_velas_respaldo(simbolo)
        
    response.raise_for_status()
    data = response.json()
    
    ohlcv = []
    for item in data:
        ohlcv.append([
            item[0],
            float(item[1]),
            float(item[2]),
            float(item[3]),
            float(item[4]),
            float(item[5])
        ])
    return ohlcv

def obtener_velas_respaldo(simbolo):
    coin_map = {'BTCUSDT': 'bitcoin', 'ETHUSDT': 'ethereum', 'SOLUSDT': 'solana'}
    coin_id = coin_map.get(simbolo, 'bitcoin')
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=2"
    res = requests.get(url, timeout=10)
    res.raise_for_status()
    prices = res.json().get('prices', [])
    return [[p[0], p[1], p[1], p[1], p[1], 0] for p in prices[-50:]]

def analizar_mercado(simbolo):
    try:
        ohlcv = obtener_velas_directas(simbolo)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['sma_short'] = df['close'].rolling(window=9).mean()
        df['sma_long'] = df['close'].rolling(window=21).mean()
        
        ultima_corta = df['sma_short'].iloc[-1]
        ultima_larga = df['sma_long'].iloc[-1]
        penultima_corta = df['sma_short'].iloc[-2]
        penultima_larga = df['sma_long'].iloc[-2]
        
        if penultima_corta <= penultima_larga and ultima_corta > ultima_larga:
            return "BUY", df['close'].iloc[-1]
        return "HOLD", df['close'].iloc[-1]
    except Exception as e:
        print(f"Error analizando {simbolo}: {e}")
        return "ERROR", 0.0

def registrar_orden_supabase(simbolo, tipo, monto_usdt, precio, cantidad):
    if not supabase:
        return
    try:
        data = {
            'simbolo': simbolo,
            'tipo': tipo,
            'monto_usdt': monto_usdt,
            'precio_ejecucion': precio,
            'cantidad': cantidad
        }
        supabase.table('ordenes').insert(data).execute()
        print(f"📊 Orden registrada exitosamente en Supabase para {simbolo}")
    except Exception as e:
        print(f"Error al registrar orden en Supabase: {e}")

def ejecutar_compra_testnet(simbolo, asignacion_usdt):
    try:
        exchange = obtener_exchange_privado()
        simbolo_ccxt = simbolo.replace("USDT", "/USDT")
        
        # Ejecuta la compra a mercado utilizando el saldo en USDT
        orden = exchange.create_market_buy_order_requires_price(simbolo_ccxt, asignacion_usdt)
        print(f"✅ ORDEN EJECUTADA EN TESTNET: {orden['id']} | {simbolo_ccxt}")
        
        precio_ejecucion = orden.get('price', 0.0)
        cantidad = orden.get('filled', 0.0)
        
        registrar_orden_supabase(simbolo, 'BUY', asignacion_usdt, precio_ejecucion, cantidad)
    except Exception as e:
        print(f"⚠️ Error al ejecutar orden en Testnet para {simbolo}: {e}")

def iniciar_bot():
    print("🤖 Bot de Trading Autosostenible Iniciado...")
    capital = obtener_capital_operable()
    print(f"💰 Capital operable: {capital:.2f} €")
    
    if capital <= 0:
        print("⚠️ No hay capital operable disponible para operar.")
        return

    monto_por_orden = capital * PORCENTAJE_POR_OPERACION
    entradas_encontradas = 0

    for simbolo in ACTIVOS:
        senal, precio_actual = analizar_mercado(simbolo)
        if senal == "BUY":
            print(f"🚀 Señal de COMPRA detectada en {simbolo} (Precio: {precio_actual})")
            entradas_encontradas += 1
            ejecutar_compra_testnet(simbolo, monto_por_orden)
            
    if entradas_encontradas == 0:
        print("🔍 No se encontraron entradas de alta probabilidad.")

if __name__ == "__main__":
    iniciar_bot()
