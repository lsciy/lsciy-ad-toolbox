# 短视频广告素材要素分析与总结系统

基于 Python + Gemini API 的命令行工具，用于管理信息流短视频广告计划数据，解析视频素材特征，并归纳总结素材的共性规律。

## 环境要求

- Python 3.14+
- 有效的 [Gemini API Key](https://aistudio.google.com/apikey)

## 快速开始

```powershell
# 1. 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 编辑配置文件，填入 API Key
# 打开 config.toml，将 gemini_api_key 替换为你的 API Key
```

## 使用方法

### 1. 录入计划数据

```powershell
python main.py insert --plan_id "123" --category "美妆" --type "口红" --cpm 20.5 --ctr 0.05 --cvr 0.02 --roi 1.5
```

### 2. 解析视频素材

将视频文件放入 `materials/{plan_id}/` 目录，然后执行：

```powershell
python main.py parse --plan_id "123"
```

支持断点续传：已解析的视频会自动跳过。

### 3. 归纳总结

```powershell
# 按类目 + ROI 下限筛选
python main.py summarize --category "美妆" --min_roi 1.2

# 按 CPM 范围筛选
python main.py summarize --min_cpm 10 --max_cpm 50

# 全量总结
python main.py summarize
```

所有数值字段均支持 `--min_xxx` 和 `--max_xxx` 范围筛选。

## 项目结构

```
├── config.toml         # 配置文件（代理/API Key/模型/提示词）
├── data.json           # 全量数据存储
├── main.py             # CLI 主入口
├── config_loader.py    # 配置加载与代理注入
├── data_manager.py     # JSON 数据管理与 eCPM 计算
├── video_parser.py     # 视频解析模块
├── summarizer.py       # 归纳总结模块
├── materials/          # 视频素材目录
│   └── {plan_id}/
├── requirements.txt    # 依赖清单
└── README.md
```
