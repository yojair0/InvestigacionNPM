import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import numpy as np

def main():
    print("--- Cruzando Outer Metrics vs Inner Coupling ---")
    
    # 1. Configurar rutas
    script_dir = os.path.dirname(os.path.abspath(__file__))
    inner_csv = os.path.join(script_dir, '..', 'data', 'metrics', 'inner_coupling_metrics.csv')
    outer_csv = os.path.join(script_dir, '..', 'data', 'metrics', 'outer_metrics.csv')
    
    if not os.path.exists(inner_csv) or not os.path.exists(outer_csv):
        print("[ERROR] Faltan los archivos CSV. Verifica que outer_metrics.csv exista.")
        return

    # 2. Cargar datos
    df_inner = pd.read_csv(inner_csv)
    df_outer = pd.read_csv(outer_csv)
    
    # Limpiar nombres de columnas por si acaso (quitar espacios)
    df_outer.columns = df_outer.columns.str.strip().str.lower()
    
    # Buscar la columna de Fan-In externo (puede llamarse fan_in, fanin, global_fan_in)
    fan_in_col = next((col for col in df_outer.columns if 'fan' in col and 'in' in col), None)
    if not fan_in_col:
        print("[ERROR] No pude detectar la columna de Fan-In en outer_metrics.csv")
        return

    # 3. Cruzar los datasets usando el nombre del paquete
    df_merged = pd.merge(df_inner, df_outer[['package', fan_in_col]], on='package', how='inner')
    
    # 4. Crear los grupos que pidió Ñicky
    df_merged['grupo_dependencia'] = np.where(df_merged[fan_in_col] == 0, 'Fan-In = 0\n(Independientes)', 'Fan-In > 0\n(Dependencias de otros)')
    
    # 5. Calcular Estadísticas (Medias, Medianas, Outliers)
    print("\n--- ESTADÍSTICAS DE ACOPLAMIENTO DE FUNCIONES (Function Fan-Out) ---")
    for group in df_merged['grupo_dependencia'].unique():
        data_group = df_merged[df_merged['grupo_dependencia'] == group]['func_fan_out_avg']
        mean = data_group.mean()
        median = data_group.median()
        stdev = data_group.std()
        limit_3sigma = mean + (3 * stdev)
        outliers = data_group[data_group > limit_3sigma].count()
        
        print(f"\nGrupo: {group.replace(chr(10), ' ')}")
        print(f" - Paquetes: {len(data_group)}")
        print(f" - Media: {mean:.4f}")
        print(f" - Mediana: {median:.4f}")
        print(f" - Límite Outlier (3σ): {limit_3sigma:.4f}")
        print(f" - Cantidad de Outliers: {outliers}")

    # 6. Graficar Boxplots (Estilo Seaborn)
    sns.set_theme(style="whitegrid")
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('Análisis de Acoplamiento Interno según Popularidad (Global Fan-In)', fontsize=16)

    # Boxplot Funciones
    sns.boxplot(x='grupo_dependencia', y='func_fan_out_avg', data=df_merged, ax=axes[0], palette="Set2")
    axes[0].set_title('Acoplamiento Promedio de Funciones (Fan-Out)')
    axes[0].set_ylabel('Promedio de Llamadas a Otras Funciones')
    axes[0].set_xlabel('Popularidad del Paquete')

    # Boxplot Clases
    sns.boxplot(x='grupo_dependencia', y='class_fan_out_avg', data=df_merged, ax=axes[1], palette="Set3")
    axes[1].set_title('Acoplamiento Promedio de Clases (Fan-Out)')
    axes[1].set_ylabel('Promedio de Llamadas a Otras Clases')
    axes[1].set_xlabel('Popularidad del Paquete')

    plt.tight_layout()
    
    # Guardar gráfico y mostrar
    plot_path = os.path.join(script_dir, '..', 'data', 'visualizations', 'coupling_boxplots.png')
    os.makedirs(os.path.dirname(plot_path), exist_ok=True)
    plt.savefig(plot_path, dpi=300)
    print(f"\n[INFO] Gráfico guardado en: {plot_path}")
    
    plt.show()

if __name__ == '__main__':
    main()