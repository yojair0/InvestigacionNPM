#!/usr/bin/env python3
"""Genera `shortlist_top50.csv` a partir de `reporte_metricas_ucn.csv`.

Salida: `shortlist_top50.csv` con columnas: rank, package, fan_in, fan_out, risk_score
"""
import csv
import sys

def read_metrics(path):
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            try:
                r['fan_in'] = int(r.get('fan_in') or 0)
            except Exception:
                r['fan_in'] = 0
            try:
                r['fan_out'] = int(r.get('fan_out') or 0)
            except Exception:
                r['fan_out'] = 0
            try:
                r['risk_score'] = int(r.get('risk_score') or (r['fan_in'] + r['fan_out']))
            except Exception:
                r['risk_score'] = r['fan_in'] + r['fan_out']
            rows.append(r)
    return rows

def write_shortlist(rows, out_path, top_n=50):
    fieldnames = ['rank', 'package', 'fan_in', 'fan_out', 'risk_score']
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for i, r in enumerate(rows[:top_n], 1):
            pkg = r.get('package') or r.get('name') or r.get('package_name') or r.get('paquete') or ''
            w.writerow({'rank': i, 'package': pkg, 'fan_in': r['fan_in'], 'fan_out': r['fan_out'], 'risk_score': r['risk_score']})

def main():
    in_csv = 'reporte_metricas_ucn.csv'
    out_csv = 'shortlist_top50.csv'
    try:
        rows = read_metrics(in_csv)
    except FileNotFoundError:
        print(f'Error: no existe {in_csv}. Genera primero las métricas.', file=sys.stderr)
        sys.exit(2)
    rows.sort(key=lambda x: x['fan_in'], reverse=True)
    write_shortlist(rows, out_csv, top_n=50)
    print(f'Generado: {out_csv} (top 50 por fan_in interno)')

if __name__ == '__main__':
    main()
