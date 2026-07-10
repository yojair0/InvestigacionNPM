import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import numpy as np

def main():
    print("--- Generando Gráfico de Dispersión Cruzado (Outer vs Inner) ---")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    inner_coupling_csv = os.path.join(script_dir, '..', 'data', 'metrics', 'inner_coupling_metrics.csv')
    outer_csv = os.path.join(script_dir, '..', 'data', 'metrics', 'outer_metrics.csv')
    
    df_inner = pd.read_csv(inner_coupling_csv)
    df_outer = pd.read_csv(outer_csv)
    df_outer.columns = df_outer.columns.str.strip().str.lower()
    
    fan_in_col = next((col for col in df_outer.columns if 'fan' in col and 'in' in col), None)
    
    df_merged = pd.merge(df_inner, df_outer[['package', fan_in_col]], on='package', how='inner')
    
    # Etiquetar los grupos para colorearlos
    df_merged['grupo'] = np.where(df_merged[fan_in_col] == 0, 'Independientes (Fan-In = 0)', 'Base (Fan-In > 0)')

    sns.set_theme(style="darkgrid")
    plt.figure(figsize=(14, 8))
    
    # Scatter plot principal
    # Usamos escala simétrica logarítmica porque hay paquetes con 0 Fan-In y otros con 10,000+
    scatter = sns.scatterplot(
        data=df_merged, 
        x=fan_in_col, 
        y='func_fan_out_avg', 
        hue='grupo',
        size='func_count',
        sizes=(20, 600),
        alpha=0.6,
        palette=['#e74c3c', '#2ecc71']
    )
    
    plt.xscale('symlog') 
    
    plt.title('Relación Ortogonal: Popularidad Global vs Acoplamiento Interno', fontsize=16)
    plt.xlabel('Global Fan-In (Popularidad - Escala Logarítmica)', fontsize=12)
    plt.ylabel('Acoplamiento Promedio de Funciones (Fan-Out Interno)', fontsize=12)
    
    # Ajustar leyenda para que no estorbe
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', borderaxespad=0)
    plt.tight_layout()
    
    plot_path = os.path.join(script_dir, '..', 'data', 'visualizations', 'scatter_ortogonal.png')
    os.makedirs(os.path.dirname(plot_path), exist_ok=True)
    plt.savefig(plot_path, dpi=300)
    print(f"\n[INFO] Scatter Plot guardado en: {plot_path}")
    
    plt.show()

if __name__ == '__main__':
    main()