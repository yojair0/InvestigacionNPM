import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import numpy as np

def main():
    print("--- Generando Estadísticas y Gráficos Extendidos ---\n")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    inner_csv = os.path.join(script_dir, '..', 'data', 'metrics', 'inner_extended_metrics.csv')
    outer_csv = os.path.join(script_dir, '..', 'data', 'metrics', 'outer_metrics.csv')
    
    df_inner = pd.read_csv(inner_csv)
    df_outer = pd.read_csv(outer_csv)
    df_outer.columns = df_outer.columns.str.strip().str.lower()
    
    fan_in_col = next((col for col in df_outer.columns if 'fan' in col and 'in' in col), None)
    
    df_merged = pd.merge(df_inner, df_outer[['package', fan_in_col]], on='package', how='inner')
    df_merged['grupo_dependencia'] = np.where(df_merged[fan_in_col] == 0, 'Fan-In = 0\n(Independientes)', 'Fan-In > 0\n(Dependencias)')
    
    metricas = {
        'avg_dependency_centrality': 'Centralidad de Dependencias',
        'avg_lines_per_file': 'Líneas de Código por Archivo',
        'avg_function_length': 'Largo Promedio de Funciones',
        'avg_parameters_per_func': 'Cantidad de Parámetros por Función'
    }

    # Imprimir estadísticas exactas para la IA
    print("=== REPORTE ESTADÍSTICO PARA ANÁLISIS ===")
    for col, title in metricas.items():
        print(f"\n--- {title.upper()} ---")
        for group in df_merged['grupo_dependencia'].unique():
            data_group = df_merged[df_merged['grupo_dependencia'] == group][col]
            mean = data_group.mean()
            median = data_group.median()
            limit_3sigma = mean + (3 * data_group.std())
            outliers = data_group[data_group > limit_3sigma].count()
            
            print(f"Grupo: {group.replace(chr(10), ' ')}")
            print(f"  Media: {mean:.4f} | Mediana: {median:.4f} | Límite Outlier: {limit_3sigma:.4f} | Total Outliers: {outliers}")

    # Generar la grilla de 4 gráficos
    sns.set_theme(style="whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('Comparativa de Deuda Técnica: Independientes vs Paquetes Base', fontsize=18)

    axes_flat = axes.flatten()
    for i, (col, title) in enumerate(metricas.items()):
        sns.boxplot(x='grupo_dependencia', y=col, data=df_merged, ax=axes_flat[i], palette="Pastel1")
        axes_flat[i].set_title(title)
        axes_flat[i].set_ylabel('Promedio')
        axes_flat[i].set_xlabel('')

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    plot_path = os.path.join(script_dir, '..', 'data', 'visualizations', 'extended_metrics_grid.png')
    os.makedirs(os.path.dirname(plot_path), exist_ok=True)
    plt.savefig(plot_path, dpi=300)
    print(f"\n[INFO] Gráfico de grilla guardado en: {plot_path}")
    plt.show()

if __name__ == '__main__':
    main()