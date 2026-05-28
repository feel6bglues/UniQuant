import os
from typing import Optional

from py_mini_racer import MiniRacer

from ...shared.logger_factory import get_logger

logger = get_logger(__name__)


class JsExecutor:
    """
    JavaScript 执行器，用于执行 ths.js 生成加密参数
    """

    def __init__(self):
        self._js_engine: Optional[MiniRacer] = None
        self._ths_js_path = os.path.join(os.path.dirname(__file__), "js", "ths.js")
        self._initialized = False

    def _initialize(self):
        """
        初始化 JavaScript 引擎
        """
        if self._initialized:
            return

        try:
            self._js_engine = MiniRacer()

            if os.path.exists(self._ths_js_path):
                with open(self._ths_js_path, "r", encoding="utf-8") as f:
                    js_content = f.read()
                self._js_engine.eval(js_content)
                logger.info("Successfully loaded ths.js")
            else:
                logger.warning(f"ths.js file not found at {self._ths_js_path}")
                self._load_default_ths_js()

            self._add_browser_mocks()

            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize JsExecutor: {e}")
            self._initialized = False

    def _load_default_ths_js(self):
        """
        加载默认的简化版 ths.js
        """
        default_js = """
        function v() {
            var timestamp = Date.now();
            var random = Math.random().toString(36).substr(2, 9);
            var combined = timestamp + "_" + random;
            return btoa(combined);
        }
        """

        try:
            self._js_engine.eval(default_js)
            logger.info("Loaded default simplified ths.js")
        except Exception as e:
            logger.error(f"Failed to load default ths.js: {e}")

    def _add_browser_mocks(self):
        """
        添加浏览器环境模拟
        """
        browser_mocks = """
        var navigator = {
            userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36',
            platform: 'Win32',
            language: 'zh-CN',
            plugins: [],
            mimeTypes: [],
            appVersion: '5.0 (Windows)',
            appName: 'Netscape',
            vendor: 'Google Inc.',
            product: 'Gecko',
            productSub: '20030107',
            vendorSub: '',
            userLanguage: 'zh-CN',
            systemLanguage: 'zh-CN',
            browserLanguage: 'zh-CN',
            onLine: true,
            cookieEnabled: true,
            doNotTrack: null,
            maxTouchPoints: 0,
            hardwareConcurrency: 8,
            deviceMemory: 8,
            mediaCapabilities: {},
            connection: {
                effectiveType: '4g',
                rtt: 50,
                downlink: 10,
                saveData: false
            },
            serviceWorker: {
                controller: null
            }
        };
        
        var window = {
            navigator: navigator,
            location: {
                href: 'http://stock.10jqka.com.cn/',
                protocol: 'http:',
                host: 'stock.10jqka.com.cn',
                hostname: 'stock.10jqka.com.cn',
                port: '',
                pathname: '/',
                search: '',
                hash: ''
            },
            document: {
                cookie: '',
                referrer: 'http://stock.10jqka.com.cn/',
                title: '同花顺财经',
                domain: '10jqka.com.cn',
                readyState: 'complete',
                createElement: function(tag) {
                    return {
                        tagName: tag.toUpperCase(),
                        style: {},
                        innerHTML: '',
                        appendChild: function() {},
                        setAttribute: function() {},
                        getAttribute: function() { return null; }
                    };
                },
                getElementsByTagName: function() {
                    return [];
                },
                querySelector: function() {
                    return null;
                },
                body: {
                    appendChild: function() {},
                    removeChild: function() {}
                }
            },
            screen: {
                width: 1920,
                height: 1080,
                colorDepth: 24,
                pixelDepth: 24,
                availWidth: 1920,
                availHeight: 1040,
                availLeft: 0,
                availTop: 0
            },
            history: {
                length: 1
            },
            localStorage: {
                getItem: function() { return null; },
                setItem: function() {},
                removeItem: function() {}
            },
            sessionStorage: {
                getItem: function() { return null; },
                setItem: function() {},
                removeItem: function() {}
            },
            setTimeout: function(func, delay) {
                return 1;
            },
            clearTimeout: function() {},
            setInterval: function(func, interval) {
                return 1;
            },
            clearInterval: function() {},
            alert: function() {},
            confirm: function() { return true; },
            prompt: function() { return ''; }
        };
        
        if (typeof btoa === 'undefined') {
            var btoa = function(str) {
                var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
                var output = '';
                
                for (var block = 0, charCode, i = 0, map = chars; 
                     str.charAt(i | 0) || (map = '=', i % 1); 
                     output += map.charAt(63 & block >> 8 - i % 1 * 8)) {
                    charCode = str.charCodeAt(i += 3/4);
                    if (charCode > 0xFF) {
                        throw new Error("'btoa' failed: The string to be encoded contains characters outside of the Latin1 range.");
                    }
                    block = block << 8 | charCode;
                }
                
                return output;
            };
        }
        
        if (typeof atob === 'undefined') {
            var atob = function(str) {
                var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
                var output = '';
                var chr1, chr2, chr3;
                var enc1, enc2, enc3, enc4;
                var i = 0;
                
                str = str.replace(/[^A-Za-z0-9+/=]/g, '');
                
                while (i < str.length) {
                    enc1 = chars.indexOf(str.charAt(i++));
                    enc2 = chars.indexOf(str.charAt(i++));
                    enc3 = chars.indexOf(str.charAt(i++));
                    enc4 = chars.indexOf(str.charAt(i++));
                    
                    chr1 = (enc1 << 2) | (enc2 >> 4);
                    chr2 = ((enc2 & 15) << 4) | (enc3 >> 2);
                    chr3 = ((enc3 & 3) << 6) | enc4;
                    
                    output = output + String.fromCharCode(chr1);
                    
                    if (enc3 != 64) {
                        output = output + String.fromCharCode(chr2);
                    }
                    if (enc4 != 64) {
                        output = output + String.fromCharCode(chr3);
                    }
                }
                
                return output;
            };
        }
        """

        try:
            self._js_engine.eval(browser_mocks)
            logger.debug("Added browser environment mocks")
        except Exception as e:
            logger.error(f"Failed to add browser mocks: {e}")

    def generate_v_param(self) -> Optional[str]:
        """
        生成同花顺加密参数 v

        Returns:
            str: 加密参数 v，失败返回 None
        """
        try:
            self._initialize()

            if not self._initialized or not self._js_engine:
                logger.error("JsExecutor not initialized")
                return None

            v_param = self._js_engine.call("v")
            logger.debug(f"Generated v parameter: {v_param}")
            return v_param
        except Exception as e:
            logger.error(f"Failed to generate v parameter: {e}")
            return self._generate_fallback_v_param()

    def _generate_fallback_v_param(self) -> Optional[str]:
        """
        备用方案生成 v 参数
        """
        try:
            import base64
            import random
            import time

            timestamp = int(time.time() * 1000)
            random_str = "".join(
                random.choices(
                    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                    k=9,
                )
            )
            combined = f"{timestamp}_{random_str}"

            combined_bytes = combined.encode("utf-8")
            v_param = base64.b64encode(combined_bytes).decode("utf-8")

            logger.debug(f"Generated fallback v parameter: {v_param}")
            return v_param
        except Exception as e:
            logger.error(f"Failed to generate fallback v parameter: {e}")
            return None

    def generate_headers(self) -> dict:
        """
        生成包含加密参数的请求头

        Returns:
            dict: 请求头字典
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36",
            "Referer": "http://stock.10jqka.com.cn/",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
            "Connection": "keep-alive",
        }

        v_param = self.generate_v_param()
        if v_param:
            headers["Cookie"] = f"v={v_param}"
            logger.debug("Added v parameter to headers")

        return headers

    def shutdown(self):
        """
        关闭 JavaScript 引擎
        """
        if self._js_engine:
            try:
                self._js_engine.eval("window = null; navigator = null;")
                self._js_engine = None
                logger.info("JsExecutor shutdown")
            except Exception as e:
                logger.error(f"Failed to shutdown JsExecutor: {e}")
        self._initialized = False


# 全局实例
js_executor = JsExecutor()


def get_ths_headers() -> dict:
    """
    获取同花顺请求头

    Returns:
        dict: 请求头字典
    """
    return js_executor.generate_headers()


def generate_ths_v_param() -> Optional[str]:
    """
    生成同花顺加密参数 v

    Returns:
        str: 加密参数 v，失败返回 None
    """
    return js_executor.generate_v_param()
