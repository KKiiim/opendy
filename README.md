# opendy · 导游证考试刷题环境

基于 [EXAM-MASTER](https://github.com/CiE-XinYuChen/EXAM-MASTER) 的本地 Web 刷题环境。

## 安装与启动

需要 Git 和 Python 3.14（含 `venv` 和 `pip`）。在仓库根目录执行以下 macOS/Linux 命令：

```bash
git submodule update --init
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/build_question_bank.py
.venv/bin/python run_local.py
```

访问 <http://127.0.0.1:32220>，首次使用时注册并登录。按 `Ctrl+C` 停止服务。
端口被占用时，可使用 `.venv/bin/python run_local.py --port 32221`，
然后访问 <http://127.0.0.1:32221>。

## 题库

仓库中的 [data/papers](data/papers) 按试卷保存 UTF-8 JSON 题目。
上述命令从 JSON 创建本地题库，不会覆盖已有数据库中的账户和练习记录。
本地数据库与 JSON 后续不会自动同步。
登录后在「题库」选择「导入 CSV」，可下载字段模板并上传 UTF-8 编码的 CSV。
必需列为 `题号`、`题干`、`答案`、`题型`；题型支持 `单选题`、`多选题`、
`判断题` 和 `填空题`。同题号的题目会被更新。

自定义试卷选择具体分类时，按题号从小到大取题；未选择分类时仍随机抽题。

## 当前题库

随仓库提供「雷大大押题卷26」第 1 至第 6 卷，每卷包含科目一二和科目三四，
共 12 份试卷、1969 题。部分解析错误的题号未收录。

题库资料整理自网络，仅供个人学习与参考，禁止用于商业用途。相关著作权归原权利人所有，
使用时请遵守相关法律法规及权利人的授权要求。
