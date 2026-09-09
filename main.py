import os
import ccxt
import pandas as pd
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

exchange = ccxt.binance({
    'apiKey': os.environ.get("BINANCE_TESTNET_KEY", ""),
    'secret': os.environ.get("BINANCE_TESTNET_SECRET", ""),
    'enableRateLimit': True,
    'urls': {
        'api': {
            'public': 'https://api.binance.com/api/v3',
            'private': 'https://testnet.binance.vision/api/v3',
        }
    }
})

ACTIVOS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
RESERVA_SERVIDORES = 20.0

def obtener_capital_operable():
    if not supabase:
        return 100.0 - RESERVA_SERVIDORES
    res = supabase.table('depositos').select('monto').execute()
    total_depositado = sum(item['monto'] for item in res.data) if res.data else 100.0
    return max(total_depositado - RESERVA_SERVIDORES, 0.0)

def escanear_mejores_oportunidades():
    mejores = []
    for simbolo in ACTIVOS:
        try:
            bars = exchange.fetch_ohlcv(simbolo, timeframe='1h', limit=50)
            df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
            precio_actual = df.iloc[-1]['close']
            ema_actual = df.iloc[-1]['ema_200']
            
            if precio_actual > ema_actual:
                score = (precio_actual - ema_actual) / ema_actual * 100
                mejores.append({'simbolo': simbolo, 'precio': precio_actual, 'score': score})
        except Exception as e:
            print(f"Error analizando {simbolo}: {e}")
            
    mejores.sort(key=lambda x: x['score'], reverse=True)
    return mejores[0] if mejores else None

def ejecutar_orden(oportunidad, capital):
    simbolo = oportunidad['simbolo']
    precio = oportunidad['precio']
    riesgo_max = capital * 0.02
    stop_loss = precio * 0.99
    take_profit = precio * 1.02
    distancia_sl = precio - stop_loss
    cantidad = riesgo_max / distancia_sl
    
    print(f"🚀 Ejecutando compra de {cantidad:.4f} {simbolo} a {precio} USDT")
    
    if supabase:
        supabase.table('operaciones').insert({
            'simbolo': simbolo,
            'tipo_orden': 'COMPRA',
            'precio_entrada': precio,
            'cantidad': cantidad,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'score_entrada': oportunidad['score']
        }).execute()

def iniciar_bot():
    print("🤖 Bot de Trading Autosostenible Iniciado...")
    capital = obtener_capital_operable()
    print(f"💰 Capital operable: {capital:.2f} €")
    
    if capital < 10.0:
        print("⚠️ Capital insuficiente para operar.")
        return

    oportunidad = escanear_mejores_oportunidades()
    if oportunidad:
        print(f"🎯 Oportunidad detectada: {oportunidad['simbolo']} (Score: {oportunidad['score']:.2f})")
        ejecutar_orden(oportunidad, capital)
    else:
        print("🔍 No se encontraron entradas de alta probabilidad.")

if __name__ == "__main__":
    iniciar_bot()
