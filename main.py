import os
import time
import requests
import pandas as pd
from supabase import create_client

# Configuración de Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

ACTIVOS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
RESERVA_SERVIDORES = 20.0
PORCENTAJE_POR_OPERACION = 0.10

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
        
        precio_actual = df['close'].iloc[-1]

        # Cruce Dorado: Compra
        if penultima_corta <= penultima_larga and ultima_corta > ultima_larga:
            return "BUY", precio_actual
        # Cruce Muerte: Venta
        elif penultima_corta >= penultima_larga and ultima_corta < ultima_larga:
            return "SELL", precio_actual
            
        return "HOLD", precio_actual
    except Exception as e:
        print(f"Error analizando {simbolo}: {e}")
        return "ERROR", 0.0

def posicion_abierta(simbolo):
    """Comprueba si tenemos una compra previa no vendida en Supabase."""
    if not supabase:
        return None
    try:
        res = supabase.table('ordenes').select('*').eq('simbolo', simbolo).order('id', desc=True).limit(1).execute()
        if res.data and res.data[0]['tipo'].startswith('BUY'):
            return res.data[0]
    except Exception as e:
        print(f"Error consultando posición en Supabase: {e}")
    return None

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
        print(f"📊 Orden {tipo} registrada exitosamente en Supabase para {simbolo} | Precio: {precio}")
    except Exception as e:
        print(f"Error al registrar orden en Supabase: {e}")

def procesar_compra(simbolo, asignacion_usdt, precio_actual):
    if posicion_abierta(simbolo):
        print(f"ℹ️ Ya existe una posición abierta en {simbolo}. No se acumulan compras.")
        return

    cantidad = asignacion_usdt / precio_actual if precio_actual > 0 else 0.0
    registrar_orden_supabase(simbolo, 'BUY (Simulado)', asignacion_usdt, precio_actual, cantidad)

def procesar_venta(simbolo, precio_actual):
    compra = posicion_abierta(simbolo)
    if not compra:
        return

    precio_compra = float(compra.get('precio_ejecucion', 0.0))
    cantidad = float(compra.get('cantidad', 0.0))
    monto_invertido = float(compra.get('monto_usdt', 0.0))
    
    monto_venta = cantidad * precio_actual
    pnl = monto_venta - monto_invertido
    porcentaje_pnl = ((precio_actual - precio_compra) / precio_compra * 100) if precio_compra > 0 else 0.0

    print(f"📉 SEÑAL DE VENTA EN {simbolo}:")
    print(f"   - Precio Entrada: {precio_compra:.2f} | Precio Salida: {precio_actual:.2f}")
    print(f"   - Resultado (PnL): {pnl:+.2f} USDT ({porcentaje_pnl:+.2f}%)")

    registrar_orden_supabase(simbolo, f"SELL ({pnl:+.2f} USDT)", monto_venta, precio_actual, cantidad)

def iniciar_bot():
    print("🤖 Bot de Trading Autosostenible Iniciado (Timeframe: 15m)...")
    capital = obtener_capital_operable()
    print(f"💰 Capital operable: {capital:.2f} €")
    
    if capital <= 0:
        print("⚠️ No hay capital operable disponible.")
        return

    monto_por_orden = capital * PORCENTAJE_POR_OPERACION

    for simbolo in ACTIVOS:
        senal, precio_actual = analizar_mercado(simbolo)
        if senal == "BUY":
            print(f"🚀 Señal de COMPRA en {simbolo} (Precio: {precio_actual})")
            procesar_compra(simbolo, monto_por_orden, precio_actual)
        elif senal == "SELL":
            procesar_venta(simbolo, precio_actual)

if __name__ == "__main__":
    iniciar_bot()
