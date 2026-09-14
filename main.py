import os
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

# Parámetros de Riesgo Optimizados (Ratio R/R 1:2.6)
STOP_LOSS_PCT = 0.015   # 1.5%
TAKE_PROFIT_PCT = 0.040  # 4.0%

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
        url = f"https://api.binance.us/api/v3/klines?symbol={simbolo}&interval=15m&limit=60"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return [[item[0], float(item[1]), float(item[2]), float(item[3]), float(item[4]), float(item[5])] for item in data]
    except Exception:
        pass

    coin = simbolo.replace("USDT", "")
    url_alt = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={coin}&tsym=USDT&limit=60&aggregate=15"
    res_alt = requests.get(url_alt, timeout=10)
    res_alt.raise_for_status()
    data_alt = res_alt.json().get('Data', {}).get('Data', [])
    
    return [[item['time'] * 1000, item['open'], item['high'], item['low'], item['close'], item['volumeto']] for item in data_alt]

def calcular_rsi(df, window=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analizar_mercado(simbolo):
    try:
        ohlcv = obtener_velas_directas(simbolo)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Medias 12/50 para evitar entradas falsas
        df['sma_short'] = df['close'].rolling(window=12).mean()
        df['sma_long'] = df['close'].rolling(window=50).mean()
        df['rsi'] = calcular_rsi(df)
        
        precio_actual = df['close'].iloc[-1]
        rsi_actual = df['rsi'].iloc[-1]
        volumen_actual = df['volume'].iloc[-1]

        ultima_corta = df['sma_short'].iloc[-1]
        ultima_larga = df['sma_long'].iloc[-1]
        penultima_corta = df['sma_short'].iloc[-2]
        penultima_larga = df['sma_long'].iloc[-2]

        if penultima_corta <= penultima_larga and ultima_corta > ultima_larga:
            return "BUY", precio_actual, rsi_actual, volumen_actual
        elif penultima_corta >= penultima_larga and ultima_corta < ultima_larga:
            return "SELL", precio_actual, rsi_actual, volumen_actual
            
        return "HOLD", precio_actual, rsi_actual, volumen_actual
    except Exception as e:
        print(f"Error analizando {simbolo}: {e}")
        return "ERROR", 0.0, 0.0, 0.0

def posicion_abierta(simbolo):
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
        print(f"📊 Orden {tipo} registrada en Supabase para {simbolo} | Precio: {precio:.2f}")
    except Exception as e:
        print(f"Error al registrar orden en Supabase: {e}")

def evaluar_posiciones_abiertas(simbolo, precio_actual):
    compra = posicion_abierta(simbolo)
    if not compra:
        return False

    precio_compra = float(compra.get('precio_ejecucion', 0.0))
    if precio_compra <= 0:
        return False

    variacion = (precio_actual - precio_compra) / precio_compra

    if variacion <= -STOP_LOSS_PCT:
        print(f"🛑 STOP LOSS ACTIVADO en {simbolo} ({variacion*100:.2f}%)")
        procesar_venta(simbolo, precio_actual, motivo="STOP_LOSS")
        return True

    if variacion >= TAKE_PROFIT_PCT:
        print(f"🎯 TAKE PROFIT ALCANZADO en {simbolo} ({variacion*100:.2f}%)")
        procesar_venta(simbolo, precio_actual, motivo="TAKE_PROFIT")
        return True

    return False

def procesar_compra(simbolo, asignacion_usdt, precio_actual, rsi, volumen):
    if posicion_abierta(simbolo):
        print(f"ℹ️ Ya existe una posición abierta en {simbolo}.")
        return

    # Filtro de entradas con RSI entre 45 y 65
    if not (45 <= rsi <= 65):
        print(f"⚠️ Compra filtrada en {simbolo}: RSI ({rsi:.1f}) fuera del rango de impulso (45-65)")
        return

    cantidad = asignacion_usdt / precio_actual if precio_actual > 0 else 0.0
    print(f"📈 Entrada confirmada | RSI: {rsi:.1f} | Vol: {volumen:.1f}")
    registrar_orden_supabase(simbolo, 'BUY (Simulado)', asignacion_usdt, precio_actual, cantidad)

def procesar_venta(simbolo, precio_actual, motivo="CRUCE"):
    compra = posicion_abierta(simbolo)
    if not compra:
        return

    precio_compra = float(compra.get('precio_ejecucion', 0.0))
    cantidad = float(compra.get('cantidad', 0.0))
    monto_invertido = float(compra.get('monto_usdt', 0.0))
    
    monto_venta = cantidad * precio_actual
    pnl = monto_venta - monto_invertido
    porcentaje_pnl = ((precio_actual - precio_compra) / precio_compra * 100) if precio_compra > 0 else 0.0

    print(f"📉 VENTA EN {simbolo} ({motivo}): Entrada: {precio_compra:.2f} | Salida: {precio_actual:.2f} | PnL: {pnl:+.2f} USDT")
    registrar_orden_supabase(simbolo, f"SELL-{motivo} ({pnl:+.2f} USDT)", monto_venta, precio_actual, cantidad)

def iniciar_bot():
    print("🤖 Bot de Trading Autosostenible Iniciado (Estrategia 12/50 + RSI)...")
    capital = obtener_capital_operable()
    print(f"💰 Capital operable: {capital:.2f} €")
    
    if capital <= 0:
        print("⚠️ No hay capital operable disponible.")
        return

    monto_por_orden = capital * PORCENTAJE_POR_OPERACION

    for simbolo in ACTIVOS:
        senal, precio_actual, rsi_actual, volumen_actual = analizar_mercado(simbolo)
        posicion_cerrada = evaluar_posiciones_abiertas(simbolo, precio_actual)
        
        if not posicion_cerrada:
            if senal == "BUY":
                print(f"🚀 Señal de COMPRA detectada en {simbolo} (Precio: {precio_actual:.2f})")
                procesar_compra(simbolo, monto_por_orden, precio_actual, rsi_actual, volumen_actual)
            elif senal == "SELL":
                procesar_venta(simbolo, precio_actual, motivo="CRUCE")

if __name__ == "__main__":
    iniciar_bot()
