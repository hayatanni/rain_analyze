import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import re
import numpy as np

# 解析対象のCSVファイル名
# ※必要に応じて変更してください
csv_path = 'export-device-1F06AD2-messages (3).csv'

def load_data(path):
    """
    ご提示の形式（セミコロン区切り、引用符付き）に合わせてデータを読み込む関数
    形式: "Data";"Device ID";"Sequence number";"Timestamp"
    """
    parsed_rows = []
    
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                
                # 1. セミコロンで分割
                parts = line.split(';')
                
                # 2. 各要素から引用符(")を除去し、余分な空白を削除
                clean_parts = [p.strip().replace('"', '').replace("'", "") for p in parts]
                
                # 3. データ行の判定 (Data列とTimestamp列が含まれているか)
                # Data列: HEX文字列(12文字以上), Timestamp: 日付形式を含む
                if len(clean_parts) >= 4:
                    data_str = clean_parts[0]  # A列: Data (と仮定)
                    device_id = clean_parts[1] # B列: Device ID
                    timestamp = clean_parts[-1] # 末尾: Timestamp
                    
                    # ヘッダー行はスキップ ("Data"という文字そのものの場合は除外)
                    if "Data" in data_str and "Timestamp" in timestamp:
                        continue
                        
                    parsed_rows.append([data_str, device_id, timestamp])
                    
        # DataFrame化
        df = pd.DataFrame(parsed_rows, columns=['Data', 'DeviceID', 'Timestamp'])
        return df
        
    except Exception as e:
        print(f"ファイル読み込みエラー: {e}")
        return pd.DataFrame()

def decode_payload(row):
    """
    Data列(24文字HEX)を解析し、5回分の時系列データを展開する
    """
    hex_str = str(row['Data'])
    try:
        # TimestampをJSTに変換済みとして扱う
        current_time = row['Timestamp']
    except:
        return []

    try:
        # HEX文字列の正規化（0-9, a-f以外を除去）
        s = re.sub(r"[^0-9a-fA-F]", "", hex_str)
        
        # データ長不足（24文字未満）はスキップ
        if len(s) < 24:
            return []

        # --- ヘッダー情報の解析 ---
        # Byte 0: 電圧 (10進数 * 0.0125 + 1.0)
        volt_val = int(s[0:2], 16)
        voltage = (volt_val * 0.0125) + 1.0
        
        # Byte 1: 電池残量 (0-100%)
        batt_pct = int(s[2:4], 16)

        # --- 履歴データの展開 (5回分) ---
        # 1メッセージに過去10分間(2分間隔x5)のデータが含まれる
        extracted_data = []
        for i in range(5):
            # 4文字(2バイト)ずつ切り出し
            # i=0: 最新(0-2分前), i=1: 2-4分前 ...
            start_idx = 4 + (i * 4)
            end_idx = start_idx + 4
            
            # 距離(mm)のデコード
            distance_mm = int(s[start_idx:end_idx], 16)
            
            # 時間を2分ずつ過去にずらす
            record_time = current_time - pd.Timedelta(minutes=i*2)
            
            extracted_data.append({
                'Timestamp_JST': record_time,
                'Distance_mm': distance_mm,
                'Voltage_V': voltage,
                'Battery_Pct': batt_pct,
                'DeviceID': row['DeviceID']
            })
            
        return extracted_data

    except Exception:
        return []

def main():
    print("処理を開始します...")
    
    # 1. データ読み込み
    df_raw = load_data(csv_path)
    if df_raw.empty:
        print("エラー: データを読み込めませんでした。ファイル名や形式を確認してください。")
        return
    
    # 2. タイムスタンプの前処理 (UTC -> JST)
    df_raw['Timestamp'] = pd.to_datetime(df_raw['Timestamp'], errors='coerce', utc=True)
    df_raw = df_raw.dropna(subset=['Timestamp'])
    df_raw['Timestamp'] = df_raw['Timestamp'].dt.tz_convert('Asia/Tokyo')
    
    print(f"読み込み行数: {len(df_raw)} 行")

    # 3. データの展開 (1行 -> 5レコード)
    all_records = []
    for _, row in df_raw.iterrows():
        records = decode_payload(row)
        all_records.extend(records)
    
    if not all_records:
        print("エラー: 有効なデータパケットが見つかりませんでした。")
        return

    # 展開データのDataFrame化
    df_plot = pd.DataFrame(all_records)
    df_plot = df_plot.sort_values('Timestamp_JST').reset_index(drop=True)
    
    device_id = df_plot['DeviceID'].iloc[0] if not df_plot.empty else "Unknown"
    print(f"展開後データ数: {len(df_plot)} 件 (デバイスID: {device_id})")

    # --- 4. グラフ描画 ---
    print("グラフを作成中...")
    
    # スタイル設定
    plt.style.use('bmh') # 見やすいスタイル
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True, 
                                   gridspec_kw={'height_ratios': [2, 1]})
    plt.subplots_adjust(hspace=0.1) # 上下のグラフの間隔

    # 上段: 水位 (距離)
    ax1.plot(df_plot['Timestamp_JST'], df_plot['Distance_mm'], 
             color='#0072B2', marker='.', markersize=2, linestyle='-', linewidth=1, label='Distance (mm)')
    ax1.set_ylabel('Distance [mm]\n(Lower = Higher Water)', fontsize=12)
    ax1.set_title(f'Water Level Monitoring [Device: {device_id}]', fontsize=14, fontweight='bold')
    ax1.invert_yaxis() # 距離なので反転
    ax1.grid(True, which='both', linestyle='--', alpha=0.7)
    ax1.legend(loc='upper right')

    # 下段: 電圧
    ax2.plot(df_plot['Timestamp_JST'], df_plot['Voltage_V'], 
             color='#D55E00', marker='', linestyle='-', linewidth=1.5, label='Voltage (V)')
    ax2.set_ylabel('Voltage [V]', fontsize=12)
    ax2.set_title('Battery Voltage', fontsize=12)
    ax2.grid(True, which='both', linestyle='--', alpha=0.7)
    
    # 電圧軸の範囲をデータの中心に合わせて調整
    v_min = df_plot['Voltage_V'].min()
    v_max = df_plot['Voltage_V'].max()
    if not np.isnan(v_min) and not np.isnan(v_max):
        margin = 0.05
        ax2.set_ylim(v_min - margin, v_max + margin)
        
    ax2.legend(loc='lower right')

    # X軸 (時間) のフォーマット
    ax2.set_xlabel('Timestamp (JST)', fontsize=12)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    plt.xticks(rotation=45)

    plt.tight_layout()
    
    # 保存
    output_file = 'water_level_graph.png'
    plt.savefig(output_file, dpi=150)
    print(f