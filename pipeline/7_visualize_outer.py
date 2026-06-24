import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import numpy as np
import warnings

warnings.filterwarnings('ignore')

DIR_PIPELINE = os.path.dirname(os.path.abspath(__file__))
DIR_METRICS = os.path.join(os.path.dirname(DIR_PIPELINE), 'data', 'metrics')
DIR_VISUAL = os.path.join(os.path.dirname(DIR_PIPELINE), 'data', 'visualizations')

FILE_OUTER = os.path.join(DIR_METRICS, 'outer_metrics.csv')

def main():
    print("Generating outer visualizations")
    
    os.makedirs(DIR_VISUAL, exist_ok=True)
    
    if not os.path.exists(FILE_OUTER):
        print(f"Error: Not found {FILE_OUTER}")
        return
        
    df = pd.read_csv(FILE_OUTER)
    sns.set_theme(style="whitegrid", palette="muted")
    
    plt.figure(figsize=(10, 6))
    df['log_fan_in'] = np.log10(df['fan_in_total'] + 1)
    df['log_fan_out'] = np.log10(df['fan_out'] + 1)
    
    data_melted = pd.melt(df[['log_fan_in', 'log_fan_out']], var_name='Metric', value_name='Log10(Value + 1)')
    data_melted['Metric'] = data_melted['Metric'].map({'log_fan_in': 'Global Fan-In', 'log_fan_out': 'Global Fan-Out'})
    
    sns.violinplot(x='Metric', y='Log10(Value + 1)', data=data_melted, inner='quartile', cut=0)
    plt.title('Fan-in and Fan-out Distribution (Logarithmic Scale)')
    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'outer_fanin_fanout_distribution.png'), dpi=300)
    plt.close()
    
    plt.figure(figsize=(10, 6))
    df_connected = df[df['coupling_volume'] > 0].copy()
    
    sns.histplot(df_connected['global_instability'], bins=20, kde=False, color="skyblue")
    plt.title('Global Instability Distribution (I = Ce / Ca+Ce)')
    plt.xlabel('Global Instability (0 = Stable, 1 = Unstable)')
    plt.ylabel('Package Count')
    plt.axvline(x=0.5, color='red', linestyle='--', alpha=0.5, label='Midpoint (0.5)')
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'outer_instability_distribution.png'), dpi=300)
    plt.close()

    plt.figure(figsize=(10, 6))
    df_connected['log_volume'] = np.log10(df_connected['coupling_volume'] + 1)
    
    sns.scatterplot(data=df_connected, x='global_instability', y='log_volume', alpha=0.4, edgecolor=None)
    plt.title('Global Instability vs Coupling Volume (Log10)')
    plt.xlabel('Global Instability')
    plt.ylabel('Total Coupling Volume (Log10)')
    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'outer_instability_vs_volume.png'), dpi=300)
    plt.close()

    plt.figure(figsize=(10, 6))
    top_providers = df.sort_values(by='dependency_balance', ascending=False).head(10)
    
    sns.barplot(data=top_providers, x='dependency_balance', y='package', palette="viridis")
    plt.title('Top 10 Provider Packages (Fan-In > Fan-Out)')
    plt.xlabel('Dependency Balance (Ca - Ce)')
    plt.ylabel('Package')
    
    for index, value in enumerate(top_providers['dependency_balance']):
        plt.text(value, index, f' {int(value):,}', va='center')
        
    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'outer_top_providers.png'), dpi=300)
    plt.close()

    print(f"Visualizations completed in: {DIR_VISUAL}")

if __name__ == "__main__":
    main()
