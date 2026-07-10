import csv
import os
import statistics
import matplotlib.pyplot as plt

def print_stats(name, g0, gX):
    def calc(arr):
        if not arr: return "N/A"
        mean = sum(arr)/len(arr)
        stdev = statistics.pstdev(arr) if len(arr)>1 else 0
        limit = mean + 3*stdev
        out_c = sum(1 for x in arr if x > limit)
        sorted_arr = sorted(arr)
        median = sorted_arr[len(arr)//2]
        return f"Media: {mean:.2f} | Mediana: {median} | Outliers (> 3 Sigma): {out_c}"
    
    print(f"=== {name} ===")
    print(f"Grupo Independientes (Fan-In = 0): {calc(g0)}")
    print(f"Grupo Dependencias   (Fan-In > 0): {calc(gX)}")
    print("")

def main():
    fanin_path = '../data/metrics/fanin_global_report.csv'
    inner_path = '../data/metrics/inner_metrics_merged.csv'
    info_path = '../data/metrics/packages_info.csv'
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fanin_path = os.path.join(base_dir, fanin_path)
    inner_path = os.path.join(base_dir, inner_path)
    info_path = os.path.join(base_dir, info_path)

    inner_data = {}
    if os.path.exists(inner_path):
        with open(inner_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                pkg = row.get('package', '')
                try:
                    inner_data[pkg] = {'c': int(row.get('classes', 0)), 'f': int(row.get('functions', 0))}
                except: pass

    files_data = {}
    if os.path.exists(info_path):
        with open(info_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                pkg = row.get('package', '')
                try:
                    files_data[pkg] = int(row.get('file_count', 0))
                except: pass

    g0_classes, gX_classes = [], []
    g0_funcs, gX_funcs = [], []
    g0_files, gX_files = [], []
    
    fanin0_x, fanin0_y = [], []
    faninX_x, faninX_y = [], []

    if os.path.exists(fanin_path):
        with open(fanin_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                pkg = row.get('package')
                fan_in = 0
                try:
                    fan_in = int(row.get('fan_in_total', 0))
                except: pass
                
                if pkg in inner_data and pkg in files_data:
                    c = inner_data[pkg]['c']
                    func = inner_data[pkg]['f']
                    file_count = files_data[pkg]
                    
                    if fan_in == 0:
                        g0_classes.append(c)
                        g0_funcs.append(func)
                        g0_files.append(file_count)
                        fanin0_x.append(fan_in)
                        fanin0_y.append(func)
                    else:
                        gX_classes.append(c)
                        gX_funcs.append(func)
                        gX_files.append(file_count)
                        faninX_x.append(fan_in)
                        faninX_y.append(func)

    print("--- RESULTADOS NUMERICOS SEGMENTADOS ---")
    print_stats("CLASES INTERNAS", g0_classes, gX_classes)
    print_stats("FUNCIONES INTERNAS", g0_funcs, gX_funcs)
    print_stats("CANTIDAD DE ARCHIVOS", g0_files, gX_files)

    def draw_segmented_boxplot(group0, groupX, title, ylabel, filename):
        if not group0 or not groupX: return
        plt.figure(figsize=(8,6))
        plt.boxplot([group0, groupX])
        plt.xticks([1, 2], ['Fan-In = 0', 'Fan-In > 0'])
        plt.title(title)
        plt.ylabel(ylabel)
        plt.yscale('symlog') 
        out_path = os.path.join(base_dir, f'../data/metrics/{filename}')
        plt.savefig(out_path)
        plt.close()

    draw_segmented_boxplot(g0_classes, gX_classes, 'Comparativa Segmentada: Clases', 'N de Clases (Escala SymLog)', 'grafico_A_clases.png')
    draw_segmented_boxplot(g0_funcs, gX_funcs, 'Comparativa Segmentada: Funciones', 'N de Funciones (Escala SymLog)', 'grafico_B_funciones.png')
    draw_segmented_boxplot(g0_files, gX_files, 'Comparativa Segmentada: Archivos', 'N de Archivos (Escala SymLog)', 'grafico_C_archivos.png')

    if fanin0_y and faninX_y:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
        ax1.scatter(fanin0_x, fanin0_y, c='red', alpha=0.5)
        ax1.set_title('Grupo: Fan-In = 0')
        ax1.set_xlabel('Fan-In')
        ax1.set_ylabel('Funciones Internas')
        
        ax2.scatter(faninX_x, faninX_y, c='blue', alpha=0.5)
        ax2.set_title('Grupo: Fan-In > 0')
        ax2.set_xlabel('Fan-In')
        
        plt.tight_layout()
        out_scatter = os.path.join(base_dir, '../data/metrics/grafico_D_scatter_separado.png')
        plt.savefig(out_scatter)
        plt.close()
    
    print("--- GRAFICOS GENERADOS CON EXITO ---")

if __name__ == '__main__':
    main()
