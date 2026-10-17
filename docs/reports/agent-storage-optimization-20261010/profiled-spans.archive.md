# 原始 Trace 归档

原始 `profiled-spans.json` 为 109321321 字节，超过 GitHub 单文件限制。仓库保存无损压缩文件 `profiled-spans.json.gz`；本地原始文件保留并忽略，不删除、不改写。

原始内容 SHA-256：`62b89f75cb24e0870ba3bb6f4a72d7680ea6a806e171e2eb7d765ec24cb3568e`。压缩后重新解压计算哈希，结果一致。

需要原 JSON 时，在此目录执行：

```python
import gzip
import shutil
from pathlib import Path

raw = Path("profiled-spans.json")
with gzip.open("profiled-spans.json.gz", "rb") as source, raw.open("xb") as target:
    shutil.copyfileobj(source, target)
```

使用独占创建模式，已有本地原始文件时不会覆盖。
