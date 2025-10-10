import threading
import logging
import pymysql
from queue import Queue, Empty
from config import Config


class DatabasePool:
    """数据库连接池"""
    
    def __init__(self, max_connections=10):
        self.max_connections = max_connections
        self.pool = Queue(maxsize=max_connections)
        self.active_connections = 0
        self.lock = threading.Lock()
        
        # 预创建一些连接
        self._fill_pool()
        
    def _fill_pool(self):
        """填充连接池"""
        with self.lock:
            while self.active_connections < self.max_connections and not self.pool.full():
                try:
                    conn = self._create_connection()
                    self.pool.put(conn)
                    self.active_connections += 1
                    logging.debug(f"创建数据库连接，当前连接数: {self.active_connections}")
                except Exception as e:
                    logging.error(f"创建数据库连接失败: {e}")
                    break
    
    def _create_connection(self):
        """创建新的数据库连接"""
        return pymysql.connect(**Config.MYSQL_CONFIG)
    
    def get_connection(self, timeout=30):
        """获取数据库连接"""
        try:
            # 尝试从池中获取连接
            conn = self.pool.get(block=True, timeout=timeout)
            
            # 检查连接是否还活着
            if not self._is_connection_alive(conn):
                logging.warning("检测到死连接，重新创建")
                conn.close()
                conn = self._create_connection()
            
            return conn
            
        except Empty:
            # 池中没有可用连接，尝试创建新连接
            with self.lock:
                if self.active_connections < self.max_connections:
                    try:
                        conn = self._create_connection()
                        self.active_connections += 1
                        logging.debug(f"创建新连接，当前连接数: {self.active_connections}")
                        return conn
                    except Exception as e:
                        logging.error(f"创建数据库连接失败: {e}")
                        raise
                else:
                    raise Exception("数据库连接池已满，无法获取连接")
    
    def return_connection(self, conn):
        """归还数据库连接到池中"""
        if conn and self._is_connection_alive(conn):
            try:
                self.pool.put(conn, block=False)
                logging.debug("连接已归还到连接池")
            except:
                # 池已满，关闭连接
                conn.close()
                with self.lock:
                    self.active_connections -= 1
                logging.debug(f"连接池已满，关闭连接，当前连接数: {self.active_connections}")
        else:
            # 连接已死，关闭并减少计数
            if conn:
                conn.close()
            with self.lock:
                self.active_connections -= 1
            logging.debug(f"关闭死连接，当前连接数: {self.active_connections}")
    
    def _is_connection_alive(self, conn):
        """检查连接是否还活着"""
        try:
            conn.ping(reconnect=False)
            return True
        except:
            return False
    
    def close_all(self):
        """关闭所有连接"""
        logging.info("正在关闭所有数据库连接...")
        
        # 关闭池中的连接
        while not self.pool.empty():
            try:
                conn = self.pool.get(block=False)
                conn.close()
            except Empty:
                break
            except Exception as e:
                logging.error(f"关闭连接时出错: {e}")
        
        with self.lock:
            self.active_connections = 0
        
        logging.info("所有数据库连接已关闭")


class DatabaseManager:
    """数据库管理器，提供便捷的数据库操作接口"""
    
    def __init__(self):
        self.pool = DatabasePool(max_connections=Config.MAX_CONCURRENT_TRANSLATIONS + 2)
    
    def execute_with_retry(self, operation_func, *args, max_retries=3, **kwargs):
        """带重试的数据库操作执行"""
        for attempt in range(max_retries):
            conn = None
            try:
                conn = self.pool.get_connection()
                result = operation_func(conn, *args, **kwargs)
                self.pool.return_connection(conn)
                return result
                
            except pymysql.err.OperationalError as e:
                if conn:
                    self.pool.return_connection(conn)
                
                error_code = e.args[0]
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # 2, 4, 6秒
                    logging.warning(f"数据库操作失败 ({error_code}): {e}, {wait_time}秒后重试 ({attempt + 1}/{max_retries})")
                    import time
                    time.sleep(wait_time)
                    continue
                else:
                    logging.error(f"数据库操作达到最大重试次数: {e}")
                    raise
                    
            except Exception as e:
                if conn:
                    self.pool.return_connection(conn)
                logging.error(f"数据库操作失败: {e}")
                raise
    
    def insert_task(self, task_data):
        """幂等性插入任务数据 - 如果task_id已存在则更新"""
        def _upsert_operation(conn, task):
            with conn.cursor() as cursor:
                # 使用 ON DUPLICATE KEY UPDATE 实现幂等性
                sql = '''
                    INSERT INTO mps_task_result (
                        task_id, status, create_time, video_name, url,
                        output_path, vtt_url, en_vtt, username
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        status = VALUES(status),
                        video_name = VALUES(video_name),
                        url = VALUES(url),
                        output_path = VALUES(output_path),
                        vtt_url = COALESCE(NULLIF(VALUES(vtt_url), ''), vtt_url),
                        en_vtt = COALESCE(NULLIF(VALUES(en_vtt), ''), en_vtt),
                        username = VALUES(username),
                        updated_at = CURRENT_TIMESTAMP
                '''
                affected_rows = cursor.execute(sql, (
                    task.get("TaskId"),
                    task.get("Status"),
                    task.get("CreateTime"),
                    task.get("VideoName"),
                    task.get("Url"),
                    task.get("OutputPath"),
                    task.get("VttUrl"),
                    task.get("EnVtt"),
                    task.get("username")
                ))
                
                if affected_rows == 1:
                    logging.info(f"成功插入任务数据：{task.get('TaskId')}")
                elif affected_rows == 2:
                    logging.info(f"成功更新任务数据：{task.get('TaskId')} (已存在)")
                else:
                    logging.warning(f"任务数据无变化：{task.get('TaskId')}")
                    
            conn.commit()
        
        return self.execute_with_retry(_upsert_operation, task_data)
    
    def check_task_exists(self, task_id):
        """检查任务是否已存在"""
        def _check_operation(conn, task_id):
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM mps_task_result WHERE task_id = %s", (task_id,))
                return cursor.fetchone()[0] > 0
        
        return self.execute_with_retry(_check_operation, task_id)
    
    def update_en_vtt(self, task_id, en_vtt_url):
        """更新英文字幕URL"""
        def _update_operation(conn, task_id, en_vtt_url):
            with conn.cursor() as cursor:
                sql = "UPDATE mps_task_result SET en_vtt = %s WHERE task_id = %s"
                cursor.execute(sql, (en_vtt_url, task_id))
            conn.commit()
            logging.info(f"成功更新英文字幕URL：{task_id}")
        
        return self.execute_with_retry(_update_operation, task_id, en_vtt_url)
    
    def close(self):
        """关闭数据库管理器"""
        self.pool.close_all()


# 全局数据库管理器实例
db_manager = DatabaseManager()