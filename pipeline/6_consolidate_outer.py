import pandas as pd
import os

DIR_PIPELINE = os.path.dirname(os.path.abspath(__file__))
DIR_METRICS = os.path.join(os.path.dirname(DIR_PIPELINE), 'data', 'metrics')

FILE_PKGS = os.path.join(DIR_METRICS, 'packages_info.csv')
FILE_FANIN = os.path.join(DIR_METRICS, 'fanin_global_report.csv')
FILE_FANOUT = os.path.join(DIR_METRICS, 'fanout_report.csv')
FILE_OUT = os.path.join(DIR_METRICS, 'outer_metrics.csv')

def main():
    print("Consolidating outer metrics")
    
    df_pkgs = pd.read_csv(FILE_PKGS, usecols=['package', 'version', 'size_bytes'])
    df_fanin = pd.read_csv(FILE_FANIN)
    df_fanout = pd.read_csv(FILE_FANOUT)
    
    df_merged = df_pkgs.merge(df_fanin, on='package', how='left')
    df_merged = df_merged.merge(df_fanout, on='package', how='left')
    
    cols_to_fill = ['fan_in_total', 'fan_out', 'dependencies_count']
    for col in cols_to_fill:
        if col in df_merged.columns:
            df_merged[col] = df_merged[col].fillna(0)
    
    ca = df_merged['fan_in_total'].astype(float)
    if 'fan_out' in df_merged.columns:
        ce = df_merged['fan_out'].astype(float)
    else:
        ce = df_merged['dependencies_count'].astype(float)
    
    sum_ca_ce = ca + ce
    df_merged['global_instability'] = 0.0
    
    mask = sum_ca_ce > 0
    df_merged.loc[mask, 'global_instability'] = ce[mask] / sum_ca_ce[mask]
    df_merged['global_instability'] = df_merged['global_instability'].round(4)
    
    df_merged['coupling_volume'] = sum_ca_ce.astype(int)
    df_merged['dependency_balance'] = (ca - ce).astype(int)
    
    final_cols = [
        'package', 'version', 'size_bytes',
        'fan_in_total', 'fan_out',
        'global_instability', 'coupling_volume', 'dependency_balance'
    ]
    
    valid_cols = [c for c in final_cols if c in df_merged.columns]
    df_final = df_merged[valid_cols]
    
    df_final.to_csv(FILE_OUT, index=False)
    print(f"Success: {len(df_final)} packages consolidated. Output: {FILE_OUT}")

if __name__ == "__main__":
    main()
