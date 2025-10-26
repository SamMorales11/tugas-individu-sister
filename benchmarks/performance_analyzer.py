# performance_analyzer.py
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import numpy as np

# Atur style global agar grafik terlihat profesional
sns.set_theme(style="whitegrid")
plt.rcParams['figure.figsize'] = (10, 6)
plt.rcParams['figure.dpi'] = 100

def create_lock_manager_graph():
    """Grafik 1: Latency Lock Acquire (Biaya Konsensus Raft)"""
    
    # Data Teoretis Lock Manager
    data_lock = {
        'Nodes': ['1 Node (Lokal)', '3 Nodes (Raft)', '5 Nodes (Raft)'],
        'Latency_ms': [5, 150, 220],
        'Tipe_Sistem': ['Single-Node (Non-Raft)', 'Distributed (Raft)', 'Distributed (Raft)']
    }
    df_lock = pd.DataFrame(data_lock)

    plt.figure()
    # Menggunakan barplot untuk membandingkan biaya latency
    sns.barplot(x='Nodes', y='Latency_ms', hue='Tipe_Sistem', data=df_lock, 
                palette={'Single-Node (Non-Raft)': '#4c72b0', 'Distributed (Raft)': '#c44e52'}, 
                dodge=False)

    plt.title('Grafik 1: Latency Lock Acquire (Biaya Konsensus Raft)', fontsize=14)
    plt.ylabel('Latency Rata-rata (milidetik)', fontsize=12)
    plt.xlabel('Konfigurasi Node', fontsize=12)
    plt.legend(title='Tipe Sistem')
    plt.yticks(np.arange(0, 250, 50))
    plt.show()


def create_queue_throughput_graph():
    """Grafik 2: Scalability Throughput (Consistent Hashing)"""

    # Data Teoretis Queue System
    data_queue = {
        'Nodes': [1, 2, 3, 4],
        'Throughput_Msg_per_sec': [1500, 3050, 4500, 5800]
    }
    df_queue = pd.DataFrame(data_queue)

    plt.figure()
    # Menggunakan lineplot untuk menunjukkan kenaikan throughput linier
    sns.lineplot(x='Nodes', y='Throughput_Msg_per_sec', data=df_queue, 
                 marker='o', color='#55a868', linewidth=2.5)

    plt.title('Grafik 2: Skalabilitas Throughput Agregat (Consistent Hashing)', fontsize=14)
    plt.ylabel('Throughput (Pesan/detik)', fontsize=12)
    plt.xlabel('Jumlah Node Aktif', fontsize=12)
    plt.xticks(data_queue['Nodes'])
    plt.ylim(0, 6500)
    plt.grid(axis='y', linestyle='--', alpha=0.6)
    plt.show()


def create_cache_cost_graph():
    """Grafik 3: Biaya Konsistensi (Protokol MESI)"""
    
    # Data Teoretis Cache Coherence
    data_cache = {
        'Operasi': ['Baca (Cache Hit)', 'Baca (Miss/Fetch)', 'Tulis (Invalidate)'],
        'Latency_ms': [0.5, 10, 150],
        'Kategori': ['Read Path', 'Read Path', 'Write Path']
    }
    df_cache = pd.DataFrame(data_cache)

    plt.figure()
    # Menggunakan barplot untuk membandingkan latency antar operasi
    order = ['Baca (Cache Hit)', 'Baca (Miss/Fetch)', 'Tulis (Invalidate)'] 
    sns.barplot(x='Operasi', y='Latency_ms', data=df_cache, 
                palette={'Read Path': '#4c72b0', 'Write Path': '#c44e52'}, 
                order=order, hue='Kategori', dodge=False)

    plt.title('Grafik 3: Biaya Latency Operasi Cache (Protokol MESI)', fontsize=14)
    plt.ylabel('Latency Rata-rata (milidetik)', fontsize=12)
    plt.xlabel('Jenis Operasi', fontsize=12)
    plt.xticks(rotation=15, ha='right')
    plt.show()

# --- Jalankan Semua Grafik ---
if __name__ == "__main__":
    create_lock_manager_graph()
    create_queue_throughput_graph()
    create_cache_cost_graph()