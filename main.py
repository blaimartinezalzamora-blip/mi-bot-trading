import os
import time
import hmac
import hashlib
import requests
import pandas as pd
from supabase import create_client

# Configuración de Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

# Credenciales Binance Testnet
BINANCE_API_KEY = os.environ.get("BINANCE_TESTNET_KEY", "")
BINANCE_SECRET = os.environ.get("BINANCE_TESTNET_SECRET", "")

ACTIVOS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
RESERVA_SERVIDORES = 20.0
PORCENTAJE_POR_OPERACION = 0.10  # 10% del capital disponible por entrada

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
    try:
        url = f"https://api.binance.us/api/v3/klines?symbol={simbolo}&interval=15m&limit=50"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return [[item[0], float(item[1]), float(item[2]), float(item[3]), float(item[4]), float(item[5])] for item in data]
    except Exception:
        pass

    coin = simbolo.replace("USDT", "")
    url_alt = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={coin}&tsym=USDT&limit=50&aggregate=15"
    res_alt = requests.get(url_alt, timeout=10)
    res_alt.raise_for_status()
    data_alt = res_alt.json().get('Data', {}).get('Data', [])
    
    return [[item['time'] * 1000, item['open'], item['high'], item['low'], item['close'], item['volumeto']] for item in data_alt]

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
        url = "https://testnet.binance.vision/api/v3/order"
        timestamp = int(time.time() * 1000)
        
        params = {
            'symbol': simbolo,
            'side': 'BUY',
            'type': 'MARKET',
            'quoteOrderQty': f"{asignacion_usdt:.2f}",
            'timestamp': timestamp
        }
        
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(BINANCE_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
        
        headers = {
            'X-MBX-APIKEY': BINANCE_API_KEY,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        }
        
        full_url = f"{url}?{query_string}&signature={signature}"
        res = requests.post(full_url, headers=headers, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            order_id = data.get('orderId', 'N/A')
            print(f"✅ ORDEN EJECUTADA EN TESTNET: {order_id} | {simbolo}")
            
            # Obtener precio y cantidad ejecutados
            fills = data.get('fills', [])
            precio = float(fills[0]['price']) if fills else 0.0
            cantidad = float(data.get('executedQty', 0.0))
            
            registrar_orden_supabase(simbolo, 'BUY', asignacion_usdt, precio, cantidad)
        else:
            print(f"⚠️ Error al ejecutar orden directa HTTP {res.status_code}: {res.text}")
            # Si la Testnet restringe por geobloqueo directo, registramos la simulación localmente
            registrar_orden_supabase(simbolo, 'BUY (Simulado)', asignacion_usdt, 0.0, 0.0)
            
    except Exception as e:
        print(f"⚠️ Excepción al ejecutar orden en Testnet para {simbolo}: {e}")

def iniciar_bot():
    print("🤖 Bot de Trading Autosostenible Iniciado (Timeframe: 15m)...")
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
