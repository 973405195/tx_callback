# 字幕翻译服务部署指南

## 快速部署

### 1. 环境准备
```bash
# Ubuntu/Debian
sudo apt update && sudo apt install python3 python3-pip python3-venv

# CentOS/RHEL
sudo yum install python3 python3-pip
```

### 2. 配置环境变量
```bash
# 复制环境变量模板
cp .env.template .env

# 编辑配置文件，填入真实信息
nano .env
```

**重要配置项：**
- `MYSQL_PASSWORD`: 数据库密码
- `TENCENT_SECRET_ID`: 腾讯云密钥ID
- `TENCENT_SECRET_KEY`: 腾讯云密钥KEY
- `GEMINI_API_KEY`: Gemini API密钥

### 3. 一键部署
```bash
chmod +x deploy.sh
./deploy.sh
```

### 4. 验证部署
```bash
# 检查服务状态
sudo systemctl status tx-callback

# 查看日志
sudo journalctl -u tx-callback -f

# 测试接口
curl http://localhost:8787/
```

## 手动部署

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 启动服务
```bash
python tx_callback.py
```

## 运维命令

### 服务控制
```bash
# 启动服务
sudo systemctl start tx-callback

# 停止服务
sudo systemctl stop tx-callback

# 重启服务
sudo systemctl restart tx-callback

# 查看状态
sudo systemctl status tx-callback
```

### 日志管理
```bash
# 实时查看日志
sudo journalctl -u tx-callback -f

# 查看最近日志
sudo journalctl -u tx-callback --since "1 hour ago"

# 查看应用日志
tail -f logs/service.log
```

### 故障排查
```bash
# 检查配置
python3 -c "from config import Config; print('配置正常')"

# 检查端口占用
netstat -tlnp | grep 8787

# 检查进程
ps aux | grep tx_callback
```

## 功能说明

### 主要功能
1. **MPS回调处理**: 接收腾讯云MPS的任务完成通知
2. **字幕翻译**: 自动下载中文字幕并翻译成英文
3. **COS上传**: 将翻译后的英文字幕上传到腾讯云COS
4. **数据库更新**: 更新任务记录中的英文字幕URL

### 处理流程
```
MPS回调 → 解析数据 → 快速响应 → 后台翻译任务
              ↓
下载字幕 → 调用Gemini翻译 → 上传COS → 更新数据库
```

### 异步处理
- 主服务立即响应MPS回调，避免超时
- 后台线程处理耗时的翻译任务
- 自动重试机制处理失败任务

## 安全说明

⚠️ **重要**: 确保`.env`文件权限设置正确
```bash
chmod 600 .env
```

⚠️ **不要**将敏感信息提交到代码仓库
- 使用`.gitignore`忽略`.env`文件
- 定期轮换API密钥