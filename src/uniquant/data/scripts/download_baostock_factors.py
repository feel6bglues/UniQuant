import baostock as bs
import pandas as pd
import os
import datetime
from tqdm import tqdm

from ...shared.time_provider import get_time_provider
from uniquant.shared.logger_factory import get_logger

# ================= 配置区域 =================
# 数据保存目录
OUTPUT_DIR = "data/baostock_factors"
# 起始日期 (A股早期)
START_DATE = "1990-01-01"
# 结束日期 (默认为今天)
END_DATE = get_time_provider().now().strftime("%Y-%m-%d")
# ===========================================

logger = get_logger(__name__)

def init_baostock():
    """登录 Baostock"""
    lg = bs.login()
    if lg.error_code != '0':
        logger.error(f"Baostock 登录失败: {lg.error_msg}")
        return False
    logger.info(f"Baostock 登录成功 (版本: {bs.__version__})")
    return True

def get_stock_list():
    """获取全市场股票列表"""
    logger.info("正在获取全市场股票列表...")
    # 使用 query_stock_basic 获取更完整的基础数据
    rs = bs.query_stock_basic()
    
    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())
    
    if not data_list:
        logger.warning("未获取到股票列表数据，尝试使用 query_all_stock")
        # 尝试使用 query_all_stock 作为备选
        rs = bs.query_all_stock(day=END_DATE)
        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())
    
    df_stocks = pd.DataFrame(data_list, columns=rs.fields)
    
    # 保存全市场股票列表到 data/all_stock_codes.csv
    stock_codes_path = "data/all_stock_codes.csv"
    df_stocks.to_csv(stock_codes_path, index=False, encoding='utf-8-sig')
    logger.info(f"已保存全市场股票列表到 {stock_codes_path}")
    
    # 简单的过滤：剔除指数，只保留股票 (根据需求调整)
    # 通常 code 以 sh.6, sh.9, sz.0, sz.3, bj.4, bj.8 等开头
    # 这里不做强制过滤，全量下载，由用户后续清洗
    logger.info(f"共获取到 {len(df_stocks)} 只证券代码")
    return df_stocks

def download_factor(code):
    """下载单只股票的复权因子"""
    # query_adjust_factor 获取复权因子
    # frequency="d" 日频, adjustflag="3" 默认为不复权数据没意义，因子本身是调节用的
    # 注意：Baostock 的 adjust_factor 接口返回的是每一天的复权因子
    rs = bs.query_adjust_factor(code=code, start_date=START_DATE, end_date=END_DATE)
    
    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())
    
    if not data_list:
        return None
        
    df = pd.DataFrame(data_list, columns=rs.fields)
    
    # 数据类型转换
    # dividOperateDate: 除权除息日期
    # foreAdjustFactor: 前复权因子
    # backAdjustFactor: 后复权因子
    # adjustFactor: 调整因子
    try:
        if 'dividOperateDate' in df.columns:
            df['dividOperateDate'] = pd.to_datetime(df['dividOperateDate'])
        cols_to_float = ['foreAdjustFactor', 'backAdjustFactor', 'adjustFactor']
        for col in cols_to_float:
            if col in df.columns:
                df[col] = df[col].astype(float)
    except Exception as e:
        logger.error(f"数据格式转换错误 {code}: {e}")
        
    return df

def main():
    # 1. 创建目录
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        logger.info(f"创建目录: {OUTPUT_DIR}")

    # 2. 登录
    if not init_baostock():
        return

    try:
        # 3. 获取股票列表
        df_stocks = get_stock_list()
        codes = df_stocks['code'].tolist()
        
        # 4. 遍历下载
        # 使用 tqdm 显示进度条
        pbar = tqdm(codes)
        for code in pbar:
            pbar.set_description(f"Processing {code}")
            
            try:
                # 检查文件是否已存在 (可选，防止中断后重跑浪费时间)
                save_path = os.path.join(OUTPUT_DIR, f"{code}.csv")
                if os.path.exists(save_path):
                    continue

                df_factor = download_factor(code)
                
                if df_factor is not None and not df_factor.empty:
                    # 保存为 CSV
                    df_factor.to_csv(save_path, index=False, encoding='utf-8')
                
            except Exception as inner_e:
                logger.error(f"处理 {code} 时发生异常: {inner_e}")
                # 重新登录以防连接断开
                bs.logout()
                bs.login()

    except Exception as e:
        logger.error(f"主程序异常: {e}")
    finally:
        # 5. 登出
        bs.logout()
        logger.info("程序结束，已退出 Baostock。")

if __name__ == "__main__":
    main()
