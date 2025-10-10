import os
import re
import requests
import json
import time
import tempfile
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from qcloud_cos import CosConfig, CosS3Client
from config import Config

class SubtitleTranslator:
    def __init__(self):
        self.gemini_api_key = Config.GEMINI_API_KEY
        self.cos_client = self._init_cos_client()
        self.temp_dir = Path(Config.TEMP_DIR)
        self.temp_dir.mkdir(exist_ok=True)
        
        # 创建线程池来控制并发翻译任务
        self.executor = ThreadPoolExecutor(
            max_workers=Config.MAX_CONCURRENT_TRANSLATIONS,
            thread_name_prefix="translator"
        )
        self._shutdown_lock = threading.Lock()
        self._is_shutdown = False
        
    def _init_cos_client(self):
        """初始化COS客户端"""
        config = CosConfig(
            Region=Config.COS_CONFIG['region'],
            SecretId=Config.COS_CONFIG['secret_id'],
            SecretKey=Config.COS_CONFIG['secret_key']
        )
        return CosS3Client(config)
    
    def process_translation_async(self, task_data):
        """异步处理翻译任务，使用线程池控制并发"""
        with self._shutdown_lock:
            if self._is_shutdown:
                logging.warning(f"翻译器已关闭，忽略任务: {task_data['task_id']}")
                return
            
            try:
                future = self.executor.submit(self._process_translation_sync, task_data)
                logging.info(f"翻译任务已提交到线程池: {task_data['task_id']}")
                
                # 添加完成回调
                future.add_done_callback(lambda f: self._task_done_callback(f, task_data['task_id']))
                
            except Exception as e:
                logging.error(f"提交翻译任务失败: {task_data['task_id']}, 错误: {e}")
    
    def _task_done_callback(self, future, task_id):
        """任务完成回调"""
        try:
            future.result()  # 这会抛出任务中的异常（如果有的话）
        except Exception as e:
            logging.error(f"翻译任务执行失败: {task_id}, 错误: {e}")
    
    def shutdown(self):
        """关闭翻译器，等待所有任务完成"""
        with self._shutdown_lock:
            if self._is_shutdown:
                return
            self._is_shutdown = True
            
        logging.info("正在关闭翻译器...")
        self.executor.shutdown(wait=True)
        logging.info("翻译器已关闭")
    
    def _process_translation_sync(self, task_data):
        """同步处理翻译任务，带有智能错误恢复"""
        task_id = task_data['task_id']
        vtt_url = task_data['vtt_url']
        username = task_data['username']
        
        # 添加重试计数器
        retry_count = task_data.get('retry_count', 0)
        max_task_retries = 3  # 整个任务最多重试3次
        
        try:
            logging.info(f"开始翻译任务: {task_id} (第{retry_count + 1}次尝试)")
            
            # 1. 下载中文字幕
            local_srt_path = self._download_subtitle(vtt_url, task_id)
            
            # 2. 翻译字幕
            en_srt_path = self._translate_subtitle(local_srt_path)
            
            # 3. 上传英文字幕（传入中文字幕URL用于路径推导）
            en_vtt_url = self._upload_english_subtitle(en_srt_path, task_id, vtt_url)
            
            # 4. 更新数据库
            self._update_database(task_id, en_vtt_url)
            
            # 5. 清理临时文件
            self._cleanup_files([local_srt_path, en_srt_path])
            
            logging.info(f"翻译任务完成: {task_id} -> {en_vtt_url}")
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"翻译任务失败: {task_id} (第{retry_count + 1}次), 错误: {error_msg}")
            
            # 分析错误类型，决定是否重试
            should_retry = self._should_retry_task(error_msg, retry_count, max_task_retries)
            
            if should_retry:
                retry_count += 1
                delay = min(2 ** retry_count * 60, 1800)  # 2分钟、4分钟、8分钟，最大30分钟
                
                logging.info(f"任务 {task_id} 将在 {delay/60:.1f} 分钟后重试 (第{retry_count + 1}次)")
                
                # 创建重试任务
                retry_task = {
                    **task_data,
                    'retry_count': retry_count
                }
                
                # 延迟重新提交任务
                def delayed_retry():
                    time.sleep(delay)
                    if not self._is_shutdown:
                        logging.info(f"重新提交任务: {task_id}")
                        self.process_translation_async(retry_task)
                
                # 在新线程中执行延迟重试
                retry_thread = threading.Thread(target=delayed_retry, daemon=True)
                retry_thread.start()
            else:
                logging.error(f"任务 {task_id} 彻底失败，不再重试。错误: {error_msg}")
    
    def _should_retry_task(self, error_msg, retry_count, max_retries):
        """根据错误类型和重试次数判断是否应该重试任务"""
        if retry_count >= max_retries:
            return False
        
        error_msg_lower = error_msg.lower()
        
        # 不应重试的错误类型
        permanent_errors = [
            "字幕文件不存在 (404)",
            "无权限访问字幕文件 (403)",
            "客户端错误 400",
            "客户端错误 401", 
            "客户端错误 403",
            "解析srt文件失败",
            "api未返回有效的翻译内容"
        ]
        
        for permanent_error in permanent_errors:
            if permanent_error.lower() in error_msg_lower:
                logging.info(f"检测到永久性错误，不重试: {permanent_error}")
                return False
        
        # 应该重试的错误类型
        retryable_errors = [
            "503 server error",
            "service unavailable", 
            "rate limited",
            "网络错误",
            "连接错误",
            "请求超时",
            "下载超时",
            "所有gemini模型均失败",
            "服务器错误",
            "死连接"
        ]
        
        for retryable_error in retryable_errors:
            if retryable_error.lower() in error_msg_lower:
                logging.info(f"检测到可重试错误: {retryable_error}")
                return True
        
        # 默认情况下，如果不确定错误类型，且重试次数较少，则重试
        if retry_count < 2:
            logging.info(f"未知错误类型，尝试重试: {error_msg[:100]}")
            return True
        
        return False
    
    def _download_subtitle(self, vtt_url, task_id):
        """下载字幕文件，带有强化重试和智能等待"""
        try:
            # 使用配置的超时时间，增加强化重试机制
            max_retries = 5
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    # 计算等待时间：指数退避 + 随机抖动
                    if attempt > 0:
                        base_delay = min(1.5 ** attempt, 30)  # 1.5, 2.25, 3.4, 5.1, 7.6秒，最大30秒
                        jitter = base_delay * 0.2 * (0.5 + 0.5 * time.time() % 1)  # ±20%随机抖动
                        wait_time = base_delay + jitter
                        logging.info(f"字幕下载第{attempt + 1}次重试，等待 {wait_time:.1f} 秒...")
                        time.sleep(wait_time)
                    
                    logging.info(f"尝试下载字幕: {vtt_url} (第{attempt + 1}次)")
                    
                    # 创建会话，支持连接复用和重连
                    session = requests.Session()
                    
                    # 设置重试适配器
                    from requests.adapters import HTTPAdapter
                    from urllib3.util.retry import Retry
                    
                    retry_strategy = Retry(
                        total=3,
                        connect=2,
                        read=2,
                        status_forcelist=[500, 502, 503, 504],
                        backoff_factor=0.3,
                        raise_on_status=False
                    )
                    
                    adapter = HTTPAdapter(max_retries=retry_strategy)
                    session.mount("http://", adapter)
                    session.mount("https://", adapter)
                    
                    # 设置请求头，模拟浏览器
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                        'Accept': 'text/plain,text/vtt,text/srt,*/*',
                        'Accept-Encoding': 'gzip, deflate',
                        'Connection': 'keep-alive',
                    }
                    
                    response = session.get(
                        vtt_url, 
                        headers=headers,
                        timeout=Config.HTTP_DOWNLOAD_TIMEOUT,
                        stream=True,
                        allow_redirects=True
                    )
                    
                    # 检查响应状态
                    if response.status_code == 404:
                        raise Exception(f"字幕文件不存在 (404): {vtt_url}")
                    elif response.status_code == 403:
                        raise Exception(f"无权限访问字幕文件 (403): {vtt_url}")
                    elif response.status_code >= 500:
                        raise requests.exceptions.HTTPError(f"服务器错误 {response.status_code}")
                    
                    response.raise_for_status()
                    
                    # 检查内容类型和长度
                    content_type = response.headers.get('Content-Type', '').lower()
                    content_length = response.headers.get('Content-Length')
                    
                    if content_length:
                        content_length = int(content_length)
                        if content_length == 0:
                            raise Exception("字幕文件为空")
                        elif content_length > 50 * 1024 * 1024:  # 50MB限制
                            raise Exception(f"字幕文件过大: {content_length} bytes")
                    
                    local_path = self.temp_dir / f"{task_id}_zh.srt"
                    
                    # 流式写入文件，带进度监控
                    total_size = 0
                    with open(local_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                total_size += len(chunk)
                                
                                # 防止无限大文件
                                if total_size > 50 * 1024 * 1024:
                                    raise Exception("下载的文件过大，中止下载")
                    
                    # 验证下载的文件
                    if total_size == 0:
                        raise Exception("下载的文件为空")
                    
                    # 简单验证文件格式（检查是否包含时间戳）
                    with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
                        first_lines = f.read(1000)  # 读取前1000字符
                        if not re.search(r'\d{2}:\d{2}:\d{2}', first_lines):
                            logging.warning(f"字幕文件格式可能有问题: {local_path}")
                    
                    logging.info(f"字幕下载完成: {local_path} ({total_size} bytes)")
                    return str(local_path)
                    
                except requests.exceptions.Timeout as e:
                    last_error = f"下载超时: {e}"
                    logging.warning(f"下载超时 (第{attempt + 1}次): {vtt_url}")
                    continue
                    
                except requests.exceptions.ConnectionError as e:
                    last_error = f"连接错误: {e}"
                    logging.warning(f"连接错误 (第{attempt + 1}次): {e}")
                    continue
                    
                except requests.exceptions.HTTPError as e:
                    status_code = getattr(e.response, 'status_code', 'unknown') if hasattr(e, 'response') else 'unknown'
                    last_error = f"HTTP错误 {status_code}: {e}"
                    
                    # 对于某些HTTP错误，不值得重试
                    if str(status_code) in ['400', '401', '403', '404']:
                        logging.error(f"HTTP客户端错误 {status_code}，停止重试")
                        break
                    else:
                        logging.warning(f"HTTP服务器错误 {status_code} (第{attempt + 1}次): {e}")
                        continue
                        
                except requests.exceptions.RequestException as e:
                    last_error = f"请求异常: {e}"
                    logging.warning(f"请求异常 (第{attempt + 1}次): {e}")
                    continue
                    
                except Exception as e:
                    last_error = f"下载失败: {e}"
                    logging.warning(f"下载失败 (第{attempt + 1}次): {e}")
                    continue
            
            # 所有重试都失败了
            raise Exception(f"字幕下载彻底失败，已重试 {max_retries} 次。最后错误: {last_error}")
            
        except Exception as e:
            raise Exception(f"下载字幕失败: {e}")
    
    def _translate_subtitle(self, srt_path):
        """翻译字幕文件"""
        try:
            # 读取字幕文件
            with open(srt_path, 'r', encoding='utf-8') as f:
                srt_content = f.read()
            
            # 解析SRT
            srt_data = self._parse_srt(srt_content)
            if not srt_data:
                raise Exception("解析SRT文件失败")
            
            # 构建翻译文本
            translation_text = ""
            for entry in srt_data:
                translation_text += f"[LINE_{entry['seq_num']}]{entry['content']}\n"
            
            # 调用Gemini翻译
            translated_text = self._call_gemini_api(translation_text)
            
            # 解析翻译结果
            translations = {}
            for line in translated_text.split('\n'):
                line = line.strip()
                if line:
                    match = re.match(r'\[LINE_(\d+)\](.*)', line)
                    if match:
                        line_num = int(match.group(1))
                        content = match.group(2).strip()
                        
                        import string
                        # 定义要保留的标点符号
                        keep_punctuation = '!? '
                        # 创建要去除的标点符号（所有标点符号减去要保留的）
                        punctuation_to_remove = ''.join(c for c in string.punctuation if c not in keep_punctuation)
                        
                        # 清理内容：去除多余标点符号
                        cleaned_content = content.strip(punctuation_to_remove + '')
                        translations[line_num] = cleaned_content
            
            # 重建SRT文件
            en_srt_path = srt_path.replace('_zh.srt', '_en.srt')
            with open(en_srt_path, 'w', encoding='utf-8') as f:
                for entry in srt_data:
                    seq_num = entry['seq_num']
                    if seq_num in translations:
                        f.write(f"{seq_num}\n{entry['timestamp']}\n{translations[seq_num]}\n\n")
            
            logging.info(f"字幕翻译完成: {en_srt_path}")
            return en_srt_path
            
        except Exception as e:
            raise Exception(f"翻译字幕失败: {e}")
    
    def _parse_srt(self, srt_text):
        """解析SRT文件"""
        pattern = r'(\d+)\s+(\d{2}:\d{2}:\d{2}[.,]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[.,]\d{3})\s+([\s\S]*?)(?=\n\s*\n\s*\d+\s+\d{2}:\d{2}:\d{2}|$)'
        entries = re.findall(pattern, srt_text)
        
        srt_data = []
        for seq_num, timestamp, content in entries:
            try:
                srt_data.append({
                    'seq_num': int(seq_num),
                    'timestamp': timestamp.strip(),
                    'content': content.strip()
                })
            except (ValueError, TypeError):
                continue
        
        return srt_data
    
    def _call_gemini_api(self, text):
        """调用Gemini API翻译，带有强化重试机制"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{Config.GEMINI_MODEL}:streamGenerateContent?alt=sse&key={self.gemini_api_key}"
        
        headers = {"Content-Type": "application/json"}
        
        prompt = f"""
        你是一位专业的英文字幕翻译专家。我将提供带有行标记[LINE_数字]的视频字幕，请将其翻译成自然、地道的美国英语。

        重要要求：
        1. 必须保留每行开头的[LINE_数字]标记
        2. 确保英语翻译自然流畅，符合母语者表达习惯
        3. 保持每行独立翻译
        4. 不要跳过任何行
        5. 不要合并或拆分行
        6. 翻译后的每行必须以原始的[LINE_数字]开头
        7. 时态问题，结合上下文保持一致
        8. 不许出现英文语法错误
        
        请翻译以下字幕：
        {text}"""
        
        data = {
            "contents": [
                {"parts": [{"text": prompt}]}
            ]
        }
        
        last_error = None
        max_retries = 5
        
        for attempt in range(max_retries):
            try:
                # 计算等待时间：指数退避 + 随机抖动
                if attempt > 0:
                    base_delay = min(2 ** attempt, 60)  # 2, 4, 8, 16, 60秒
                    jitter = base_delay * 0.1 * (0.5 + 0.5 * time.time() % 1)  # ±10%随机抖动
                    wait_time = base_delay + jitter
                    logging.info(f"Gemini API 第{attempt + 1}次重试，等待 {wait_time:.1f} 秒...")
                    time.sleep(wait_time)
                
                logging.info(f"尝试调用 Gemini API (第{attempt + 1}次尝试)")
                
                response = requests.post(
                    url, 
                    headers=headers, 
                    json=data, 
                    stream=True, 
                    timeout=Config.GEMINI_API_TIMEOUT
                )
                
                # 检查HTTP状态码
                if response.status_code == 429:  # 速率限制
                    raise requests.exceptions.HTTPError("Rate limited", response=response)
                elif response.status_code == 503:  # 服务不可用
                    raise requests.exceptions.HTTPError("Service unavailable", response=response)
                elif response.status_code >= 500:  # 服务器错误
                    raise requests.exceptions.HTTPError("Server error", response=response)
                
                response.raise_for_status()
                
                # 解析流式响应
                result_content = ""
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith("data: "):
                            try:
                                line_data = json.loads(line[6:])
                                if "candidates" in line_data and line_data["candidates"]:
                                    candidate = line_data["candidates"][0]
                                    if "content" in candidate and "parts" in candidate["content"]:
                                        parts = candidate["content"]["parts"]
                                        if parts and len(parts) > 0 and "text" in parts[0]:
                                            text_part = parts[0]["text"]
                                            result_content += text_part
                            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                                logging.debug(f"跳过无效的响应行: {line[:100]}..., 错误: {e}")
                                continue
                
                if not result_content.strip():
                    raise Exception("API未返回有效的翻译内容")
                
                logging.info(f"Gemini API 调用成功 (第{attempt + 1}次尝试)")
                return result_content
                
            except requests.exceptions.Timeout as e:
                last_error = f"请求超时: {e}"
                logging.warning(f"Gemini API 超时 (第{attempt + 1}次): {e}")
                continue
                
            except requests.exceptions.HTTPError as e:
                status_code = getattr(e.response, 'status_code', 'unknown')
                last_error = f"HTTP错误 {status_code}: {e}"
                
                # 对于某些错误，不值得重试
                if status_code in [400, 401, 403]:  # 客户端错误，直接失败
                    logging.error(f"Gemini API 客户端错误 {status_code}，停止重试")
                    break
                elif status_code in [429, 503]:  # 可重试的服务器错误
                    logging.warning(f"Gemini API 服务器错误 {status_code} (第{attempt + 1}次): {e}")
                    continue
                else:
                    logging.warning(f"Gemini API 未知HTTP错误 {status_code} (第{attempt + 1}次): {e}")
                    continue
                    
            except requests.exceptions.RequestException as e:
                last_error = f"网络错误: {e}"
                logging.warning(f"Gemini API 网络错误 (第{attempt + 1}次): {e}")
                continue
                
            except Exception as e:
                last_error = f"未知错误: {e}"
                logging.error(f"Gemini API 未知错误 (第{attempt + 1}次): {e}")
                continue
        
        # 所有重试都失败了
        raise Exception(f"Gemini API 调用失败，已重试 {max_retries} 次。最后错误: {last_error}")
    
    def _upload_english_subtitle(self, en_srt_path, task_id, zh_vtt_url):
        """上传英文字幕到COS，与中文字幕同目录"""
        try:
            # 从中文字幕URL提取COS路径
            # zh_vtt_url格式: https://zh-video-1322637479.cos.ap-shanghai.myqcloud.com/en_video/zh_video/测试音色克隆/测试8.srt
            base_url = Config.COS_BASE_URL
            if zh_vtt_url.startswith(base_url):
                zh_cos_path = zh_vtt_url[len(base_url):].lstrip('/')
                # zh_cos_path: en_video/zh_video/测试音色克隆/测试8.srt
                
                # 构建英文字幕路径：在文件名前加en_前缀
                path_parts = zh_cos_path.split('/')
                filename = path_parts[-1]  # 测试8.srt
                en_filename = f"en_{filename}"  # en_测试8.srt
                path_parts[-1] = en_filename
                en_cos_path = '/'.join(path_parts)  # en_video/zh_video/测试音色克隆/en_测试8.srt
            else:
                # 如果URL格式不符合预期，使用原来的逻辑
                filename = os.path.basename(en_srt_path)
                en_cos_path = f"en_subtitles/{task_id}/{filename}"
            
            logging.info(f"上传英文字幕: {zh_cos_path} -> {en_cos_path}")
            
            # 上传文件
            self.cos_client.upload_file(
                Bucket=Config.COS_CONFIG['bucket'],
                Key=en_cos_path,
                LocalFilePath=en_srt_path
            )
            
            # 返回完整URL
            en_vtt_url = f"{base_url}/{en_cos_path}"
            logging.info(f"英文字幕上传完成: {en_vtt_url}")
            return en_vtt_url
            
        except Exception as e:
            raise Exception(f"上传英文字幕失败: {e}")
    
    def _update_database(self, task_id, en_vtt_url):
        """更新数据库中的英文字幕URL"""
        from db_pool import db_manager
        
        try:
            db_manager.update_en_vtt(task_id, en_vtt_url)
        except Exception as e:
            logging.error(f"更新数据库失败: {task_id}, 错误: {e}")
            raise
    
    def _cleanup_files(self, file_paths):
        """清理临时文件"""
        for path in file_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    logging.debug(f"清理临时文件: {path}")
            except Exception as e:
                logging.warning(f"清理文件失败 {path}: {e}")

# 全局翻译器实例
translator = SubtitleTranslator()