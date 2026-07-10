import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

def main():
    print("--- Iniciando Control de Calidad y Verificación de Datos (AST) ---")
    
    # 1. Rutas de archivos
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, '..', 'data', 'metrics', 'inner_coupling_metrics.csv')
    
    if not os.path.exists(csv_path):
        print(f"[ERROR] No se encontró el archivo CSV en: {csv_path}")
        return
        
    # 2. Cargar el dataset verificado
    df = pd.read_csv(csv_path)
    
    metrics = {
        'class_count': 'Total de Clases por Paquete',
        'func_count': 'Total de Funciones por Paquete'
    }
    
    print("\n=== REPORTE AUDITADO DE DATOS CRUDOS ===")
    for col, title in metrics.items():
        data = df[col]
        mean = data.mean()
        median = data.median()
        stdev = data.std()
        max_val = data.max()
        limit_3sigma = mean + (3 * stdev)
        outliers = data[data > limit_3sigma].count()
        
        print(f"\n--- {title.upper()} ---")
        print(f"  - Total Paquetes Procesados: {len(data)}")
        print(f"  - Media Real (Mean): {mean:.2f}")
        print(f"  - Mediana Real (Median): {median:.2f}")
        print(f"  - Desviación Estándar (Stdev): {stdev:.2f}")
        print(f"  - Valor Máximo Detectado (Max): {max_val}")
        print(f"  - Umbral de Outliers (Media + 3σ): {limit_3sigma:.2f}")
        print(f"  - Cantidad de Outliers Reales: {outliers}")

    # 3. Re-graficar para contrastar con el chat anterior
    sns.set_theme(style="whitegrid")
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    fig.suptitle('Validación de Distribuciones Estructurales Iniciales', fontsize=14)
    
    # Boxplot Clases
    sns.boxplot(y='class_count', data=df, ax=axes[0], color='#f39c12')
    axes[0].set_title('Distribución de Clases (Auditado)')
    axes[0].set_ylabel('Cantidad de Clases')
    
    # Boxplot Funciones
    sns.boxplot(y='func_count', data=df, ax=axes[1], color='#3498db')
    axes[1].set_title('Distribución de Funciones (Auditado)')
    axes[1].set_ylabel('Cantidad de Funciones')
    
    plt.tight_layout()
    
    # Guardar gráfico verificado
    plot_path = os.path.join(script_dir, '..', 'data', 'visualizations', 'verified_initial_distributions.png')
    os.makedirs(os.path.dirname(plot_path), exist_ok=True)
    plt.savefig(plot_path, dpi=300)
    print(f"\n[INFO] Gráfico de auditoría guardado en: {plot_path}")
    
    plt.show()

if __name__ == '__main__':
    main()