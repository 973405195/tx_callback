#!/bin/bash

# 字幕翻译服务部署脚本

echo "开始部署字幕翻译服务..."

# 1. 检查Python环境
python3 --version || { echo "需要Python 3.6+"; exit 1; }

# 2. 创建项目目录
PROJECT_DIR="/opt/tx_callback"
sudo mkdir -p $PROJECT_DIR
sudo chown $USER:$USER $PROJECT_DIR
cd $PROJECT_DIR

# 3. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 4. 安装依赖
pip install --upgrade pip
pip install -r requirements.txt

# 5. 创建必要目录
mkdir -p /tmp/subtitles
mkdir -p logs
chmod 755 /tmp/subtitles

# 6. 配置环境变量
if [ ! -f .env ]; then
    echo "请先配置.env文件！"
    echo "复制.env.template为.env并填入真实配置"
    exit 1
fi

# 7. 验证配置
python3 -c "
from config import Config
try:
    Config.validate_config() if hasattr(Config, 'validate_config') else print('配置加载成功')
    print('✅ 配置验证通过')
except Exception as e:
    print(f'❌ 配置验证失败: {e}')
    exit(1)
"

# 8. 创建systemd服务
sudo tee /etc/systemd/system/tx-callback.service > /dev/null <<EOF
[Unit]
Description=TX Callback Service with Translation
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$PROJECT_DIR/venv/bin
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/venv/bin/python tx_callback.py
Restart=always
RestartSec=10
StandardOutput=append:$PROJECT_DIR/logs/service.log
StandardError=append:$PROJECT_DIR/logs/error.log

[Install]
WantedBy=multi-user.target
EOF

# 9. 启用并启动服务
sudo systemctl daemon-reload
sudo systemctl enable tx-callback
sudo systemctl start tx-callback

# 10. 检查服务状态
echo "检查服务状态..."
sleep 3
sudo systemctl status tx-callback

# 11. 测试服务
echo "测试服务..."
curl -f http://localhost:8787/ && echo "✅ 服务运行正常" || echo "❌ 服务测试失败"

echo "部署完成！"
echo "日志查看: sudo journalctl -u tx-callback -f"
echo "服务控制: sudo systemctl {start|stop|restart|status} tx-callback"