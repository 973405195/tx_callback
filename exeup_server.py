from flask import Flask, send_from_directory, jsonify
import os

app = Flask(__name__)

# 文件所在目录
DIST_DIR = os.path.join(os.path.dirname(__file__), "dist")

# 如果目录不存在就创建
os.makedirs(DIST_DIR, exist_ok=True)

# 版本文件路径
VERSION_FILE = os.path.join(DIST_DIR, "version.json")

# 路由：获取版本信息
@app.route("/version.json")
def version():
    if os.path.exists(VERSION_FILE):
        return send_from_directory(DIST_DIR, "version.json")
    return jsonify({"error": "version.json not found"}), 404

# 路由：下载 exe 文件
@app.route("/<filename>")
def download(filename):
    file_path = os.path.join(DIST_DIR, filename)
    if os.path.exists(file_path):
        return send_from_directory(DIST_DIR, filename, as_attachment=True)
    return jsonify({"error": f"{filename} not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8796)