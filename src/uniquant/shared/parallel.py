import multiprocessing as mp


def get_optimal_workers(max_workers: int = 8) -> int:
    return min(mp.cpu_count(), max_workers)


def worker_init():
    pass
