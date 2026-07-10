import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

def main():
    print("--- Generando Análisis de Correlaciones (Spearman) ---")
    
    # 1. Configurar rutas
    script_dir = os.path.dirname(os.path.abspath(__file__))
    inner_coupling_csv = os.path.join(script_dir, '..', 'data', 'metrics', 'inner_coupling_metrics.csv')
    inner_ext_csv = os.path.join(script_dir, '..', 'data', 'metrics', 'inner_extended_metrics.csv')
    outer_csv = os.path.join(script_dir, '..', 'data', 'metrics', 'outer_metrics.csv')
    
    # 2. Cargar todos los datos
    df_coupling = pd.read_csv(inner_coupling_csv)
    df_ext = pd.read_csv(inner_ext_csv)
    df_outer = pd.read_csv(outer_csv)
    df_outer.columns = df_outer.columns.str.strip().str.lower()
    
    fan_in_col = next((col for col in df_outer.columns if 'fan' in col and 'in' in col), None)
    
    # 3. Unir todo en un solo Megadataset usando el nombre del paquete
    df_merged = pd.merge(df_coupling, df_ext, on='package', how='inner')
    df_merged = pd.merge(df_merged, df_outer[['package', fan_in_col]], on='package', how='inner')
    
    # Seleccionar solo las columnas numéricas para la correlación
    columnas_numericas = df_merged.select_dtypes(include=['float64', 'int64'])
    
    # 4. Calcular Matriz de Correlación de Spearman (ideal para datos con outliers en MSR)
    matriz_corr = columnas_numericas.corr(method='spearman')
    
    # 5. Graficar el Mapa de Calor (Heatmap)
    plt.figure(figsize=(14, 10))
    sns.set_theme(style="white")
    
    # Crear una máscara para ocultar la mitad superior (es redundante)
    mask = matriz_corr.isnull()
    for i in range(len(matriz_corr)):
        for j in range(i+1, len(matriz_corr)):
            mask.iloc[i, j] = True
            
    # Dibujar el Heatmap
    sns.heatmap(matriz_corr, mask=mask, annot=True, fmt=".2f", cmap='coolwarm', 
                vmax=1, vmin=-1, center=0, square=True, linewidths=.5, 
                cbar_kws={"shrink": .8})
                
    plt.title('Mapa de Calor de Correlaciones (Spearman) - Ecosistema NPM', fontsize=18)
    plt.tight_layout()
    
    # Guardar gráfico
    plot_path = os.path.join(script_dir, '..', 'data', 'visualizations', 'correlation_heatmap.png')
    os.makedirs(os.path.dirname(plot_path), exist_ok=True)
    plt.savefig(plot_path, dpi=300)
    print(f"\n[INFO] Mapa de Calor guardado en: {plot_path}")
    
    plt.show()

if __name__ == '__main__':
    main()