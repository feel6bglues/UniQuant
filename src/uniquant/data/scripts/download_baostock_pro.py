import baostock as bs
import pandas as pd
import os
import datetime
import time
import re
from tqdm import tqdm
from uniquant.shared.logger_factory import get_logger

# 股票代码文件路径
STOCK_CODES_FILE = "data/all_stock_codes.csv"

# ================= 核心配置 =================
# 输出目录
OUTPUT_DIR = "data/baostock_factors"
# 起始日期 (A股早期)
START_DATE = "1990-01-01"
# 结束日期
END_DATE = datetime.datetime.now().strftime("%Y-%m-%d")
# 最大重试次数
MAX_RETRIES = 3
# ===========================================

logger = get_logger(__name__)

def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)
        logger.info(f"✅ 创建目录: {directory}")

def login_bs():
    """登录并保持连接"""
    bs.logout() # 先登出防止重复
    lg = bs.login()
    if lg.error_code != '0':
        logger.error(f"❌ Baostock 登录失败: {lg.error_msg}")
        return False
    logger.info("✅ Baostock 登录成功")
    return True

def is_valid_stock(code):
    """
    过滤非股票代码
    保留:
    sh.60xxxx (沪市主板), sh.68xxxx (科创板)
    sz.00xxxx (深市主板/中小板), sz.30xxxx (创业板)
    bj.4xxxxx, bj.8xxxxx (北交所)
    """
    # 正则匹配 A 股常见模式
    pattern = r'^(sh\.60|sh\.68|sz\.00|sz\.30|bj\.4|bj\.8)\d{4}$'
    return bool(re.match(pattern, code))

def get_stock_list():
    """从CSV文件获取股票代码并过滤已退市股票"""
    logger.info("⏳ 正在从CSV文件读取股票代码...")
    
    try:
        # 读取CSV文件
        df = pd.read_csv(STOCK_CODES_FILE, encoding='utf-8-sig')
        logger.info(f"✅ 读取到 {len(df)} 条记录")
        
        # 过滤已退市股票 (status=0)
        active_stocks = df[df['status'] == 1]
        logger.info(f"✅ 活跃股票数: {len(active_stocks)}")
        
        codes = []
        for row in active_stocks.itertuples(index=False):
            code = row.code
            if is_valid_stock(code):
                codes.append(code)
        
        logger.info(f"✅ 过滤后 A股股票数: {len(codes)}")
        return codes
    except Exception as e:
        logger.error(f"❌ 读取股票代码文件失败: {e}")
        # 如果读取失败，回退到使用 baostock API
        logger.info("⏳ 回退到使用 baostock API 获取股票代码...")
        rs = bs.query_all_stock(day=END_DATE)
        
        codes = []
        while (rs.error_code == '0') & rs.next():
            row = rs.get_row_data()
            code = row[0] # code is the first column
            if is_valid_stock(code):
                codes.append(code)
                
        logger.info(f"✅ 原始记录数: {len(codes)} | 过滤后 A股股票数: {len(codes)}")
        return codes

def download_with_retry(code):
    """带重试机制的下载函数"""
    for attempt in range(MAX_RETRIES):
        try:
            # 下载复权因子
            rs = bs.query_adjust_factor(code=code, start_date=START_DATE, end_date=END_DATE)
            
            # Baostock 错误处理
            if rs.error_code != '0':
                raise Exception(f"BS Error: {rs.error_msg}")
                
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            # 如果没有数据（比如刚上市或停牌），返回空DF但视为成功
            if not data_list:
                return pd.DataFrame()

            df = pd.DataFrame(data_list, columns=rs.fields)
            
            # 类型转换优化
            if 'dividOperateDate' in df.columns:
                df['dividOperateDate'] = pd.to_datetime(df['dividOperateDate'])
            for col in ['foreAdjustFactor', 'backAdjustFactor', 'adjustFactor']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    
            return df

        except Exception as e:
            # 如果是最后一次尝试，抛出异常
            if attempt == MAX_RETRIES - 1:
                logger.error(f"❌ {code} 下载失败 (最终): {e}")
                return None
            
            # 否则，稍微等待后重连重试
            time.sleep(1)
            login_bs() # 尝试重连
            
    return None

def main():
    ensure_dir(OUTPUT_DIR)
    
    if not login_bs():
        return

    # 1. 获取代码表
    all_stocks = get_stock_list()
    
    # 2. 准备进度条
    pbar = tqdm(all_stocks, desc="下载进度", unit="只")
    
    success_count = 0
    skip_count = 0
    fail_codes = []

    for code in pbar:
        save_path = os.path.join(OUTPUT_DIR, f"{code}.csv")
        
        # 3. 断点续传检查
        if os.path.exists(save_path):
            skip_count += 1
            continue
            
        # 4. 下载数据
        df = download_with_retry(code)
        
        if df is None:
            # 下载失败
            fail_codes.append(code)
        else:
            # 5. 保存数据 (即使是空的也保存，防止下次重复请求)
            # 使用 utf-8-sig 防止 Excel 打开乱码
            df.to_csv(save_path, index=False, encoding='utf-8-sig')
            success_count += 1
            
        # 更新进度条信息
        pbar.set_postfix({"跳过": skip_count, "成功": success_count, "失败": len(fail_codes)})

    bs.logout()
    logger.info("\n" + "="*50)
    logger.info("🎉 下载任务完成")
    logger.info(f"总数: {len(all_stocks)}")
    logger.info(f"成功/新下载: {success_count}")
    logger.info(f"跳过(已存在): {skip_count}")
    logger.info(f"失败: {len(fail_codes)}")
    
    if fail_codes:
        logger.info("⚠️ 失败代码列表已保存至 failed_downloads.txt")
        with open("failed_downloads.txt", "w", encoding='utf-8') as f:
            for c in fail_codes:
                f.write(c + "\n")

if __name__ == "__main__":
    main()
