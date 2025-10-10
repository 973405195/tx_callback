import logging
from datetime import datetime
from time import sleep

import pymysql
from flask import Flask, jsonify, request
from flask_cors import CORS
from config import Config
from translator import translator
from db_pool import db_manager

# 实例化 flask 对象
app = Flask(__name__)

CORS(app)


@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "service": "Tencent MPS Callback Handler",
        "timestamp": datetime.now().isoformat()
    }), 200


@app.route('/pyapi/mps/callback', methods=['POST'])
def mps_callback():
    try:
        data = request.get_json()
        print(data)
        if not data:
            logging.error("No JSON payload received")
            return jsonify({"error": "Invalid payload"}), 400

        if data.get("EventType") != "WorkflowTask":
            logging.info(f"Ignored EventType: {data.get('EventType')}")
            return jsonify({"status": "ignored"}), 200

        event = data.get("WorkflowTaskEvent", {})
        SessionContext = data.get("SessionContext", '')
        status = event.get("Status")
        task_id = event.get("TaskId")
        analysis_result_set = event.get("AiAnalysisResultSet", [])
        asr_vtt = event.get("SmartSubtitlesTaskResult", [])
        avt = ''

        if len(analysis_result_set) == 0:
            for asrv in asr_vtt:
                if asrv.get("Type") == "AsrFullTextRecognition":
                    TransTextRecognition = asrv.get("AsrFullTextTask", {})
                    output = TransTextRecognition.get("Output", {})
                    avt = output.get('SubtitlePath', '')
                    InputInfo = event.get("InputInfo", {})
                    UrlInputInfo = InputInfo.get("UrlInputInfo", {})
                    Url = UrlInputInfo.get("Url", {})

                    create_time = TransTextRecognition.get("BeginProcessTime", "")

                    video_name = None
                    if Url:
                        parts = Url.split('/')
                        if len(parts) >= 2:
                            video_name = parts[-2] + '/' + parts[-1]

                    task_data = {
                        "TaskId": task_id,
                        "Status": status,
                        "CreateTime": create_time,
                        "VideoName": video_name,
                        "Url": '',
                        "OutputPath": '',
                        "VttUrl": avt,
                        "EnVtt": '',
                        "username": SessionContext
                    }
                    db_manager.insert_task(task_data)
                    
                    # 如果有中文字幕，启动翻译任务
                    if avt and status == "SUCCESS":
                        print(f"准备启动ASR翻译任务，vtt_url: {avt}")
                        logging.info(f"准备启动ASR翻译任务，vtt_url: {avt}")
                        translation_task = {
                            "task_id": task_id,
                            "vtt_url": avt,
                            "username": SessionContext
                        }
                        try:
                            translator.process_translation_async(translation_task)
                            print(f"已启动ASR翻译任务: {task_id}")
                            logging.info(f"已启动ASR翻译任务: {task_id}")
                        except Exception as e:
                            print(f"启动ASR翻译任务失败: {task_id}, 错误: {e}")
                            logging.error(f"启动ASR翻译任务失败: {task_id}, 错误: {e}")
            return jsonify({"status": "processed", "type": "asr"}), 200  # 添加明确的返回值
        else:
            for result in event.get("AiAnalysisResultSet", []):
                if result.get("Type") == "DeLogo":
                    create_time = result.get("DeLogoTask", {}).get("BeginProcessTime", "")
                    break

            logging.info(f"Handling task: {task_id}, status: {status}")

            for result in analysis_result_set:
                if result.get("Type") == "DeLogo":
                    delogo = result.get("DeLogoTask", {})
                    if delogo.get("Status") == "SUCCESS":
                        output = delogo.get("Output", {})
                        output_path = output.get("Path", "")
                        origin_subtitle = output.get("OriginSubtitlePath", "")
                        translate_subtitle = output.get("TranslateSubtitlePath", "")

                        base_url = "https://zh-video-1322637479.cos.ap-shanghai.myqcloud.com"
                        url = base_url + output_path if output_path else ""
                        vtt_url = base_url + origin_subtitle if origin_subtitle else ""
                        en_vtt = base_url + translate_subtitle if translate_subtitle else ""

                        if vtt_url == '':
                            vtt_url = avt

                        video_name = "未知"
                        if output_path:
                            parts = output_path.split('/')
                            if len(parts) >= 2:
                                video_name = parts[-2] + '/' + parts[-1]

                        if video_name=='未知':
                            # 去掉首尾 /，然后切分
                            parts = vtt_url.split("/")
                            video_name = '/'.join(parts[-2:])
                            video_name =  video_name[:-3] + 'mp4'

                        print(f"任务 {task_id} 成功完成，视频链接：{url}")

                        task_data = {
                            "TaskId": task_id,
                            "Status": status,
                            "CreateTime": create_time,
                            "VideoName": video_name,
                            "Url": url,
                            "OutputPath": output_path,
                            "VttUrl": vtt_url,
                            "EnVtt": en_vtt,
                            "username": SessionContext
                        }
                        db_manager.insert_task(task_data)
                        
                        # 如果有中文字幕，启动翻译任务
                        print(f"调试信息: vtt_url={vtt_url}, status={status}, status类型={type(status)}")
                        logging.info(f"调试信息: vtt_url={vtt_url}, status={status}")
                        if vtt_url and status == "FINISH":
                            print(f"准备启动翻译任务，vtt_url: {vtt_url}")
                            logging.info(f"准备启动翻译任务，vtt_url: {vtt_url}")
                            translation_task = {
                                "task_id": task_id,
                                "vtt_url": vtt_url,
                                "username": SessionContext
                            }
                            try:
                                translator.process_translation_async(translation_task)
                                print(f"已启动翻译任务: {task_id}")
                                logging.info(f"已启动翻译任务: {task_id}")
                            except Exception as e:
                                print(f"启动翻译任务失败: {task_id}, 错误: {e}")
                                logging.error(f"启动翻译任务失败: {task_id}, 错误: {e}")

            return jsonify({"status": "processed", "type": "delogo"}), 200

    except Exception as e:
        print("Error handling callback")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


if __name__ == '__main__':
    # 创建临时目录
    import os
    import atexit
    
    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    
    # 注册清理函数
    def cleanup():
        logging.info("应用关闭，清理资源...")
        translator.shutdown()
        db_manager.close()
    
    atexit.register(cleanup)
    
    # 启动服务
    try:
        app.run(host='0.0.0.0', port=Config.FLASK_PORT, debug=False)
    except KeyboardInterrupt:
        logging.info("接收到中断信号")
    finally:
        cleanup()
