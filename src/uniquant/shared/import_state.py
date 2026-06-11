# -*- coding: utf-8 -*-
"""
导入状态管理模块 - 提供线程安全的导入状态跟踪

项目铁律:
1. No Magic: 所有数值常量提取到模块顶部
2. No Print: 使用logger记录日志
3. Specific Except: 捕获具体异常类型
4. Max Complexity: 函数不超过50行
5. Defensive IO: 文件操作添加超时和重试
"""
import json
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple
from datetime import datetime

from uniquant.shared.logger_factory import get_logger
from uniquant.shared.time_provider import get_time_provider

logger = get_logger('import_state')

STATE_FILE_NAME = 'import_state.json'
FINGERPRINT_KEY = 'fingerprints'
METADATA_KEY = 'metadata'


class ThreadSafeImportCounter:
    """线程安全的导入计数器"""
    
    def __init__(self):
        self._success = 0
        self._failed = 0
        self._total = 0
        self._lock = threading.Lock()
    
    def set_total(self, total: int) -> None:
        with self._lock:
            self._total = total
    
    def increment_success(self) -> None:
        with self._lock:
            self._success += 1
    
    def increment_failed(self) -> None:
        with self._lock:
            self._failed += 1
    
    def get_progress(self) -> Tuple[int, int, int, int]:
        with self._lock:
            processed = self._success + self._failed
            return self._success, self._failed, processed, self._total
    
    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                'success': self._success,
                'failed': self._failed,
                'total': self._total,
                'processed': self._success + self._failed,
            }


class ImportStateManager:
    """导入状态管理器 - 跟踪文件导入状态实现增量更新"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.state_file = self.output_dir / STATE_FILE_NAME
        self._state: Dict = self._load_state()
        self._lock = threading.Lock()
    
    def _load_state(self) -> Dict:
        if not self.state_file.exists():
            return {FINGERPRINT_KEY: {}, METADATA_KEY: {}}
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"状态文件解析失败，将重新创建: {e}")
            return {FINGERPRINT_KEY: {}, METADATA_KEY: {}}
        except OSError as e:
            logger.warning(f"读取状态文件失败: {e}")
            return {FINGERPRINT_KEY: {}, METADATA_KEY: {}}
    
    def _save_state(self) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error(f"保存状态文件失败: {e}")
    
    def _get_fingerprint_key(self, code: str, market: str) -> str:
        return f"{code}.{market.upper()}"
    
    def is_import_needed(self, code: str, market: str, source_file: Path) -> bool:
        key = self._get_fingerprint_key(code, market)
        
        with self._lock:
            if key not in self._state.get(FINGERPRINT_KEY, {}):
                return True
            
            fp = self._state[FINGERPRINT_KEY][key]
            if fp.get('status') != 'success':
                return True
            
            if not source_file.exists():
                return False
            
            try:
                current_mtime = source_file.stat().st_mtime
                current_size = source_file.stat().st_size
                stored_mtime = fp.get('mtime', 0)
                stored_size = fp.get('size', 0)
                
                return current_mtime != stored_mtime or current_size != stored_size
            except OSError as e:
                logger.debug(f"获取文件状态失败 {source_file}: {e}")
                return True
    
    def update_state(self, code: str, market: str, source_file: Path,
                     record_count: int, last_data: str, status: str = 'success') -> None:
        key = self._get_fingerprint_key(code, market)
        
        with self._lock:
            try:
                mtime = source_file.stat().st_mtime if source_file.exists() else 0
                size = source_file.stat().st_size if source_file.exists() else 0
                
                self._state.setdefault(FINGERPRINT_KEY, {})[key] = {
                    'mtime': mtime,
                    'size': size,
                    'records': record_count,
                    'last_data': last_data,
                    'status': status,
                    'updated_at': get_time_provider().now().isoformat(),
                }
                self._save_state()
            except OSError as e:
                logger.warning(f"更新状态失败 {code}.{market}: {e}")
    
    def get_state(self, code: str, market: str) -> Optional[Dict]:
        key = self._get_fingerprint_key(code, market)
        with self._lock:
            return self._state.get(FINGERPRINT_KEY, {}).get(key)
    
    def clear_state(self, code: str, market: str) -> None:
        key = self._get_fingerprint_key(code, market)
        with self._lock:
            if key in self._state.get(FINGERPRINT_KEY, {}):
                del self._state[FINGERPRINT_KEY][key]
                self._save_state()
    
    def clear_all(self) -> None:
        with self._lock:
            self._state = {FINGERPRINT_KEY: {}, METADATA_KEY: {}}
            self._save_state()
    
    def get_stats(self) -> Dict:
        with self._lock:
            fingerprints = self._state.get(FINGERPRINT_KEY, {})
            return {
                'total': len(fingerprints),
                'success': sum(1 for v in fingerprints.values() if v.get('status') == 'success'),
                'failed': sum(1 for v in fingerprints.values() if v.get('status') != 'success'),
            }
