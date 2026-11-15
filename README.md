# opendy · 导游证考试刷题环境

基于 [EXAM-MASTER](https://github.com/CiE-XinYuChen/EXAM-MASTER) 的本地 Web 刷题环境。

## 安装与启动

需要 Git 和 Python 3.14（含 `venv` 和 `pip`）。在仓库根目录执行以下 macOS/Linux 命令：

```bash
git submodule update --init
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_local.py
```

访问 <http://127.0.0.1:32220>，首次使用时注册并登录。按 `Ctrl+C` 停止服务。
端口被占用时，可使用 `.venv/bin/python run_local.py --port 32221`，
然后访问 <http://127.0.0.1:32221>。

## 题库

新建的题库为空，不会自动导入上游题目；已有数据在重启后保留。
登录后在「题库」选择「导入 CSV」，可下载字段模板并上传 UTF-8 编码的 CSV。
必需列为 `题号`、`题干`、`答案`、`题型`；题型支持 `单选题`、`多选题`、
`判断题` 和 `填空题`。同题号的题目会被更新。
