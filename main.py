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

# Parámetros de Gestión de Riesgo
STOP_LOSS_PCT = 0.015   # 1.5% de pérdida máxima
TAKE_PROFIT_PCT = 0.030  # 3.0% de beneficio objetivo

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
        
        # Medias Móviles
        df['sma_short'] = df['close'].rolling(window=9).mean()
        df['sma_long'] = df['close'].rolling(window=21).mean()
        
        # Indicador RSI para contexto
        df['rsi'] = calcular_rsi(df)
        
        precio_actual = df['close'].iloc[-1]
        rsi_actual = df['rsi'].iloc[-1]
        volumen_actual = df['volume'].iloc[-1]

        ultima_corta = df['sma_short'].iloc[-1]
        ultima_larga = df['sma_long'].iloc[-1]
        penultima_corta = df['sma_short'].iloc[-2]
        penultima_larga = df['sma_long'].iloc[-2]

        # Cruce Dorado (Compra)
        if penultima_corta <= penultima_larga and ultima_corta > ultima_larga:
            return "BUY", precio_actual, rsi_actual, volumen_actual
        # Cruce Muerte (Venta)
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
    """Comprueba si la posición abierta tocó el Stop Loss o Take Profit."""
    compra = posicion_abierta(simbolo)
    if not compra:
        return False

    precio_compra = float(compra.get('precio_ejecucion', 0.0))
    if precio_compra <= 0:
        return False

    variacion = (precio_actual - precio_compra) / precio_compra

    # Control de Stop Loss
    if variacion <= -STOP_LOSS_PCT:
        print(f"🛑 STOP LOSS ACTIVADO en {simbolo} (Caída del {variacion*100:.2f}%)")
        procesar_venta(simbolo, precio_actual, motivo="STOP_LOSS")
        return True

    # Control de Take Profit
    if variacion >= TAKE_PROFIT_PCT:
        print(f"🎯 TAKE PROFIT ALCANZADO en {simbolo} (Subida del {variacion*100:.2f}%)")
        procesar_venta(simbolo, precio_actual, motivo="TAKE_PROFIT")
        return True

    return False

def procesar_compra(simbolo, asignacion_usdt, precio_actual, rsi, volumen):
    if posicion_abierta(simbolo):
        print(f"ℹ️ Ya existe una posición abierta en {simbolo}. No se acumulan compras.")
        return

    # Filtro básico de seguridad: no comprar si el RSI indica sobrecompra extrema (> 70)
    if rsi > 70:
        print(f"⚠️ Compra descartada en {simbolo}: RSI demasiado alto ({rsi:.1f})")
        return

    cantidad = asignacion_usdt / precio_actual if precio_actual > 0 else 0.0
    print(f"📈 RSI al entrar: {rsi:.1f} | Vol: {volumen:.1f}")
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

    print(f"📉 VENTA EJECUTADA ({motivo}) EN {simbolo}:")
    print(f"   - Entrada: {precio_compra:.2f} | Salida: {precio_actual:.2f}")
    print(f"   - PnL: {pnl:+.2f} USDT ({porcentaje_pnl:+.2f}%)")

    registrar_orden_supabase(simbolo, f"SELL-{motivo} ({pnl:+.2f} USDT)", monto_venta, precio_actual, cantidad)

def iniciar_bot():
    print("🤖 Bot de Trading Autosostenible Iniciado (Timeframe: 15m + SL/TP)...")
    capital = obtener_capital_operable()
    print(f"💰 Capital operable: {capital:.2f} €")
    
    if capital <= 0:
        print("⚠️ No hay capital operable disponible.")
        return

    monto_por_orden = capital * PORCENTAJE_POR_OPERACION

    for simbolo in ACTIVOS:
        senal, precio_actual, rsi_actual, volumen_actual = analizar_mercado(simbolo)
        
        # 1. Primero evalúa si hay que cerrar posición por SL/TP
        posicion_cerrada = evaluar_posiciones_abiertas(simbolo, precio_actual)
        
        # 2. Si no se cerró por SL/TP, evalúa las señales normales
        if not posicion_cerrada:
            if senal == "BUY":
                print(f"🚀 Señal de COMPRA en {simbolo} (Precio: {precio_actual:.2f})")
                procesar_compra(simbolo, monto_por_orden, precio_actual, rsi_actual, volumen_actual)
            elif senal == "SELL":
                procesar_venta(simbolo, precio_actual, motivo="CRUCE")

if __name__ == "__main__":
    iniciar_bot()
