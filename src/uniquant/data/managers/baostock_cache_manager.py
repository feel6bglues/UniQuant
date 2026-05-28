#!/usr/bin/env python3
"""
使用 Baostock 获取全量股票代码并创建本地缓存
"""

from datetime import datetime

from ...data.sources.baostock import BaostockSource
from ...shared.logger_factory import get_logger

logger = get_logger("BaostockCacheManager")


def create_baostock_cache():
    """
    使用 Baostock 获取全量股票代码并创建本地缓存
    """
    logger.info("开始使用 Baostock 获取全量股票代码")
    
    # 创建 BaostockSource 实例
    baostock = BaostockSource()
    
    try:
        # 1. 登录 Baostock
        logger.info("1. 登录 Baostock...")
        if not baostock._login():
            logger.error("登录 Baostock 失败")
            return
        logger.info("登录 Baostock 成功")
        
        # 2. 获取全量股票代码
        logger.info("2. 获取全量股票代码...")
        # 使用系统当前日期
        current_date = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"查询日期: {current_date}")
        
        # 调用 fetch_stock_list 方法
        stock_list = baostock.fetch_stock_list(date=current_date)
        
        logger.info(f"3. 返回数据类型: {type(stock_list)}")
        logger.info(f"4. 数据是否为空: {stock_list.empty}")
        if not stock_list.empty:
            logger.info(f"5. 成功获取全量股票代码，共 {len(stock_list)} 只股票")
            logger.info(f"6. 数据列名: {list(stock_list.columns)}")
            logger.info(f"7. 前3只股票详细数据:\n{stock_list.head(3)}")
            
            # 8. 保存到本地
            output_path = "data/all_stock_codes.csv"
            temp_path = "data/all_stock_codes_temp.csv"
            logger.info(f"8. 保存到本地文件: {output_path}")
            
            # 处理数据，确保包含代码和名称列
            if "code" in stock_list.columns:
                # 处理股票代码前缀，与其他模块保持一致
                
                # 提取股票名称
                if "code_name" in stock_list.columns:
                    # 直接使用code_name作为name列
                    stock_list['name'] = stock_list['code_name']
                elif "name" in stock_list.columns:
                    # 如果已经有name列，直接使用
                    pass
                else:
                    # 如果没有名称列，设置为空
                    stock_list['name'] = ""
                
                # 保存完整的基础数据，同时添加"代码"列以兼容其他模块
                required_columns = ["code", "name"]
                # 添加"代码"列，与DataFetcher和StorageManager保持一致
                if "code" in stock_list.columns and "代码" not in stock_list.columns:
                    # 提取纯股票代码（去除前缀和后缀）
                    stock_list['代码'] = stock_list['code'].apply(lambda x: x.replace('.SH', '').replace('.SZ', '').replace('.BJ', '').replace('sh.', '').replace('sz.', '').replace('bj.', ''))
                    required_columns.append("代码")
                # 添加其他可用的基础字段
                optional_columns = ["ipoDate", "outDate", "type", "status"]
                for col in optional_columns:
                    if col in stock_list.columns:
                        required_columns.append(col)
                
                stock_codes = stock_list[required_columns]
                logger.info(f"9. 处理后的数据样例:\n{stock_codes.head(3)}")
                try:
                    import os
                    import shutil
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    # 先保存到临时文件
                    stock_codes.to_csv(temp_path, index=False, encoding='utf-8-sig')
                    # 然后重命名覆盖原文件
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    shutil.move(temp_path, output_path)
                    logger.info(f"6. 保存成功，文件大小: {os.path.getsize(output_path) / 1024:.2f} KB")
                except OSError as save_error:
                    logger.error(f"6. 保存失败: {save_error}")
                    import traceback
                    logger.error(f"错误堆栈: {traceback.format_exc()}")
                finally:
                    # 清理临时文件
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
            else:
                logger.error("6. 数据缺少代码列")
        else:
            logger.error("3. 获取全量股票代码失败，返回空数据")
            
    except (RuntimeError, ConnectionError, OSError, ValueError) as e:
        logger.error(f"操作失败: {e}")
        import traceback
        logger.error(f"错误堆栈: {traceback.format_exc()}")
    finally:
        # 登出 Baostock
        logger.info("\n7. 登出 Baostock...")
        baostock._logout()
    
    # 验证文件是否创建成功
    logger.info("\n8. 验证文件...")
    output_path = "data/all_stock_codes.csv"
    try:
        import os
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path) / 1024  # KB
            logger.info(f"✓ {output_path} - {file_size:.2f} KB")
        else:
            logger.error(f"✗ {output_path} - 不存在")
    except OSError as e:
        logger.error(f"验证文件失败: {e}")
    
    logger.info("使用 Baostock 获取全量股票代码完成")


def main():
    """
    主函数
    """
    create_baostock_cache()


if __name__ == "__main__":
    main()
