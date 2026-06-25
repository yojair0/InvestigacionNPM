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

FILE_INNER = os.path.join(DIR_METRICS, 'inner_metrics_ast.csv')

def main():
    print("Generating inner visualizations")

    os.makedirs(DIR_VISUAL, exist_ok=True)

    if not os.path.exists(FILE_INNER):
        print(f"Error: Not found {FILE_INNER}")
        return

    df = pd.read_csv(FILE_INNER)

    # Filter out binary/empty packages
    df = df.drop_duplicates(subset='package', keep='first')
    df_active = df[df['module_file_count'] > 0].copy()

    sns.set_theme(style="whitegrid", palette="muted")

    # External Instability vs Internal Coupling
    plt.figure(figsize=(10, 6))

    df_scatter = df_active[df_active['jt_ca'] + df_active['jt_ce'] > 0].copy()
    df_scatter['log_fan_out_internal'] = np.log10(df_scatter['module_internal_fan_out_mean'] + 1)

    sns.scatterplot(
        data=df_scatter,
        x='jt_instability',
        y='log_fan_out_internal',
        size='module_file_count',
        sizes=(20, 400),
        alpha=0.5,
        edgecolor=None,
        legend='brief'
    )
    plt.title('External Instability vs Internal Coupling')
    plt.xlabel('External Instability (Ce / Ca+Ce)')
    plt.ylabel('Internal Fan-Out Mean (Log10)')
    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'inner_instability_vs_coupling.png'), dpi=300)
    plt.close()
    print("Saved: inner_instability_vs_coupling.png")

    # Complexity Distribution
    plt.figure(figsize=(12, 6))

    df_violin = df_active[['function_mean', 'class_mean', 'module_decl_mean']].copy()
    df_violin.columns = ['Functions per File', 'Classes per File', 'Imports per File']

    # Apply log scale for readability
    for col in df_violin.columns:
        df_violin[col] = np.log10(df_violin[col].astype(float) + 1)

    melted = pd.melt(df_violin, var_name='Metric', value_name='Log10(Mean + 1)')

    sns.violinplot(x='Metric', y='Log10(Mean + 1)', data=melted, inner='quartile', cut=0)
    plt.title('Internal Complexity Distribution Across Packages')
    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'inner_complexity_distribution.png'), dpi=300)
    plt.close()
    print("Saved: inner_complexity_distribution.png")

    # Core Modules (Internal Fan-In Max)
    plt.figure(figsize=(12, 7))

    df_cores = df_active.nlargest(20, 'module_internal_fan_in_max').copy()
    df_cores['short_name'] = df_cores['package'].apply(lambda x: x.split('/')[-1][:20])

    colors = plt.cm.inferno(np.linspace(0.2, 0.8, len(df_cores)))
    sizes = (df_cores['module_file_count'] / df_cores['module_file_count'].max()) * 800 + 50

    plt.scatter(
        df_cores['module_internal_fan_in_max'],
        range(len(df_cores)),
        s=sizes,
        c=colors,
        alpha=0.7,
        edgecolors='white',
        linewidth=0.5
    )

    plt.yticks(range(len(df_cores)), df_cores['short_name'])
    plt.xlabel('Max Internal Fan-In (times a single file is imported)')
    plt.title('Top 20 Core Module Packages (Highest Internal Fan-In)')

    for i, row in enumerate(df_cores.itertuples()):
        plt.text(row.module_internal_fan_in_max, i, f'  {int(row.module_internal_fan_in_max):,}', va='center', fontsize=8)

    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'inner_core_modules.png'), dpi=300)
    plt.close()
    print("Saved: inner_core_modules.png")

    # Technical Debt Ranking (Outliers)
    plt.figure(figsize=(12, 7))

    df_active['total_outliers'] = (
        df_active['function_outlier_count'].astype(int) +
        df_active['class_outlier_count'].astype(int) +
        df_active['module_decl_outlier_count'].astype(int)
    )

    df_debt = df_active.nlargest(15, 'total_outliers').copy()
    df_debt['short_name'] = df_debt['package'].apply(lambda x: x.split('/')[-1][:20])

    bar_colors = sns.color_palette("YlOrRd", len(df_debt))

    plt.barh(df_debt['short_name'], df_debt['total_outliers'], color=bar_colors)
    plt.xlabel('Total Statistical Outlier Files')
    plt.title('Top 15 Packages by Structural Outliers (Functions + Classes + Imports)')
    plt.gca().invert_yaxis()

    for i, val in enumerate(df_debt['total_outliers']):
        plt.text(val, i, f'  {int(val)}', va='center', fontsize=9)

    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'inner_technical_debt.png'), dpi=300)
    plt.close()
    print("Saved: inner_technical_debt.png")

    # Used vs Unused Packages (Internal Complexity)
    plt.figure(figsize=(12, 6))
    
    df_usage = df_active.copy()
    df_usage['Usage Status'] = np.where(df_usage['jt_ca'] > 0, 'Used (Fan-In > 0)', 'Unused (Fan-In = 0)')
    
    df_box = df_usage[['Usage Status', 'function_mean', 'class_mean', 'module_decl_mean']].copy()
    df_box.columns = ['Usage Status', 'Functions/File', 'Classes/File', 'Imports/File']
    
    for col in ['Functions/File', 'Classes/File', 'Imports/File']:
        df_box[col] = np.log10(df_box[col].astype(float) + 1)
        
    melted_box = pd.melt(df_box, id_vars=['Usage Status'], var_name='Metric', value_name='Log10(Mean + 1)')
    
    sns.boxplot(x='Metric', y='Log10(Mean + 1)', hue='Usage Status', data=melted_box)
    plt.title('Internal Complexity: Used vs Unused Packages')
    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'inner_used_vs_unused.png'), dpi=300)
    plt.close()
    print("Saved: inner_used_vs_unused.png")

    # Correlation Heatmap
    plt.figure(figsize=(14, 12))
    
    cols_to_correlate = [
        'jt_ca', 'jt_ce', 'jt_instability', 'module_file_count',
        'module_decl_mean', 'module_internal_fan_in_mean', 'module_internal_fan_out_mean',
        'class_mean', 'function_mean', 'function_call_mean',
        'function_outlier_count', 'class_outlier_count'
    ]
    
    df_corr = df_active[cols_to_correlate].corr()
    
    mask = np.triu(np.ones_like(df_corr, dtype=bool))
    sns.heatmap(df_corr, mask=mask, annot=True, fmt=".2f", cmap='coolwarm', vmin=-1, vmax=1, square=True, linewidths=.5)
    
    plt.title('Correlation Heatmap of Internal and External Metrics')
    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'inner_correlation_heatmap.png'), dpi=300)
    plt.close()
    print("Saved: inner_correlation_heatmap.png")

    # Size vs Complexity
    plt.figure(figsize=(10, 6))
    
    df_scale = df_active[df_active['function_call_mean'] > 0].copy()
    df_scale['log_file_count'] = np.log10(df_scale['module_file_count'] + 1)
    df_scale['log_function_calls'] = np.log10(df_scale['function_call_mean'] + 1)
    
    sns.regplot(
        data=df_scale, 
        x='log_file_count', 
        y='log_function_calls', 
        scatter_kws={'alpha':0.5},
        line_kws={'color':'red'}
    )
    
    plt.title('Package Size vs Internal Complexity (Log10)')
    plt.xlabel('Number of Files (Log10)')
    plt.ylabel('Function Calls per File Mean (Log10)')
    plt.tight_layout()
    plt.savefig(os.path.join(DIR_VISUAL, 'inner_size_vs_complexity.png'), dpi=300)
    plt.close()
    print("Saved: inner_size_vs_complexity.png")

    # Profile of Successful Packages
    df_top = df_active.nlargest(20, 'jt_ca').copy()
    
    radar_metrics = ['function_mean', 'class_mean', 'module_decl_mean', 'module_internal_fan_out_mean', 'function_call_mean']
    radar_labels = ['Functions/File', 'Classes/File', 'Imports/File', 'Internal Fan-Out', 'Function Calls/File']
    
    top_medians = df_top[radar_metrics].median()
    all_medians = df_active[radar_metrics].median()
    
    max_vals = pd.concat([top_medians, all_medians], axis=1).max(axis=1)
    max_vals = max_vals.replace(0, 1) # Avoid division by zero
    
    top_normalized = top_medians / max_vals
    all_normalized = all_medians / max_vals
    
    N = len(radar_labels)
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1]
    
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    
    values_top = top_normalized.tolist()
    values_top += values_top[:1]
    ax.plot(angles, values_top, linewidth=2, linestyle='solid', label='Top 20 Most Used (High Fan-In)')
    ax.fill(angles, values_top, alpha=0.25)
    
    values_all = all_normalized.tolist()
    values_all += values_all[:1]
    ax.plot(angles, values_all, linewidth=2, linestyle='dashed', label='Overall Ecosystem Median')
    ax.fill(angles, values_all, alpha=0.1)
    
    plt.xticks(angles[:-1], radar_labels)
    ax.set_yticklabels([]) # Hide radial ticks
    plt.title('Internal Structural Profile: Most Used Packages vs Rest of Ecosystem', size=14, y=1.1)
    plt.legend(loc='upper right', bbox_to_anchor=(0.1, 0.1))
    plt.tight_layout()
    
    plt.savefig(os.path.join(DIR_VISUAL, 'inner_successful_profile.png'), dpi=300)
    plt.close(fig)
    print("Saved: inner_successful_profile.png")

    print(f"All inner visualizations completed in: {DIR_VISUAL}")

if __name__ == "__main__":
    main()
