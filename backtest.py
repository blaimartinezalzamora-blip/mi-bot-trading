import requests
import pandas as pd
import numpy as np

# Configuración del Backtest
SIMBOLO = "BTCUSDT"
TIMEFRAME = "15m"
DIAS_HISTORICO = 30  # Analizar los últimos 30 días
CAPITAL_INICIAL = 1000.0
PORCENTAJE_POR_TRADE = 0.10  # 10% del capital por operación

STOP_LOSS_PCT = 0.015   # 1.5%
TAKE_PROFIT_PCT = 0.030  # 3.0%
COMISION_EXCHANGE = 0.001 # 0.1% por operación (Binance estándar)

def descargar_historico(simbolo, limite=1000):
    print(f"📥 Descargando velas históricas de {simbolo}...")
    url = f"https://api.binance.us/api/v3/klines?symbol={simbolo}&interval={TIMEFRAME}&limit={limite}"
    res = requests.get(url)
    data = res.json()
    
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['volume'] = df['volume'].astype(float)
    return df

def calcular_rsi(df, window=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def ejecutar_backtest():
    df = descargar_historico(SIMBOLO)
    
    # Calcular Indicadores
    df['sma_short'] = df['close'].rolling(window=9).mean()
    df['sma_long'] = df['close'].rolling(window=21).mean()
    df['rsi'] = calcular_rsi(df)

    capital = CAPITAL_INICIAL
    posicion_abierta = False
    precio_entrada = 0.0
    monto_invertido = 0.0
    
    operaciones = []

    for i in range(21, len(df)):
        precio_actual = df['close'].iloc[i]
        high_actual = df['high'].iloc[i]
        low_actual = df['low'].iloc[i]
        
        corta_actual = df['sma_short'].iloc[i]
        larga_actual = df['sma_long'].iloc[i]
        corta_previa = df['sma_short'].iloc[i-1]
        larga_previa = df['sma_long'].iloc[i-1]
        rsi_actual = df['rsi'].iloc[i]

        # 1. Evaluar salida si hay posición abierta
        if posicion_abierta:
            # Control de Stop Loss
            if low_actual <= precio_entrada * (1 - STOP_LOSS_PCT):
                precio_salida = precio_entrada * (1 - STOP_LOSS_PCT)
                pnl = (monto_invertido * (1 - STOP_LOSS_PCT)) - monto_invertido - (monto_invertido * COMISION_EXCHANGE)
                capital += pnl
                operaciones.append({'tipo': 'SL', 'pnl': pnl, 'precio_salida': precio_salida})
                posicion_abierta = False
                continue

            # Control de Take Profit
            elif high_actual >= precio_entrada * (1 + TAKE_PROFIT_PCT):
                precio_salida = precio_entrada * (1 + TAKE_PROFIT_PCT)
                pnl = (monto_invertido * (1 + TAKE_PROFIT_PCT)) - monto_invertido - (monto_invertido * COMISION_EXCHANGE)
                capital += pnl
                operaciones.append({'tipo': 'TP', 'pnl': pnl, 'precio_salida': precio_salida})
                posicion_abierta = False
                continue

            # Venta por Cruce de Medias
            elif corta_previa >= larga_previa and corta_actual < larga_actual:
                pnl = (monto_invertido * (precio_actual / precio_entrada)) - monto_invertido - (monto_invertido * COMISION_EXCHANGE)
                capital += pnl
                operaciones.append({'tipo': 'SELL_CRUCE', 'pnl': pnl, 'precio_salida': precio_actual})
                posicion_abierta = False
                continue

        # 2. Evaluar entrada (Cruce Dorado)
        if not posicion_abierta:
            if corta_previa <= larga_previa and corta_actual > larga_actual:
                if rsi_actual <= 70:  # Filtro de RSI
                    posicion_abierta = True
                    precio_entrada = precio_actual
                    monto_invertido = capital * PORCENTAJE_POR_TRADE
                    capital -= (monto_invertido * COMISION_EXCHANGE)

    # Métricas Finales
    df_ops = pd.DataFrame(operaciones)
    ganadoras = df_ops[df_ops['pnl'] > 0] if not df_ops.empty else []
    perdedoras = df_ops[df_ops['pnl'] <= 0] if not df_ops.empty else []
    
    win_rate = (len(ganadoras) / len(df_ops) * 100) if not df_ops.empty else 0

    print("\n=== RESULTADOS DEL BACKTEST ===")
    print(f"Asset: {SIMBOLO} | Velas: 15m")
    print(f"Capital Inicial: {CAPITAL_INICIAL:.2f} USDT")
    print(f"Capital Final:   {capital:.2f} USDT")
    print(f"Beneficio Total: {capital - CAPITAL_INICIAL:+.2f} USDT ({((capital - CAPITAL_INICIAL)/CAPITAL_INICIAL)*100:+.2f}%)")
    print(f"Total Operaciones: {len(df_ops)}")
    print(f"Tasa de Acierto (Win Rate): {win_rate:.1f}%")

if __name__ == "__main__":
    ejecutar_backtest()
