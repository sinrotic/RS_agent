最终商品三塔模型：product_three_tower_final_v1

本目录提供最终模型检查点 model.pt、独立模型定义 model_definition.py 和产物清单 manifest.json。
model.pt 包含商品/用户/查询三个残差MLP的已训练参数；BGE-M3由现有模型服务提供，未嵌入该文件。
这是稳定纯三塔的版本化发布，不是v15全量续训产物。来源、模型SHA和配置详见manifest。

架构：1024维输入与输出，每塔独立1024→256→1024残差MLP，输出归一化。
用户塔聚合最近50项商品表示；一致性聚合温度0.15，<=2项使用均值。没有ID嵌入。
查询塔输入现有BGE-M3的1024维特征；商品塔使用相同BGE编码器的商品特征。
模型已接入服务，保护位为0，保留历史80件过滤和ID去重。

服务器完整服务包：
/mnt/data/luo/remote_runs/product_v16_final/export/
该目录额外包含 item_vectors.npy 和 item_ids.jsonl，共763080件商品；为避免复制约3GB向量，本地未下载这两项。
单独在本地加载model.pt可以使用三个塔的前向；按商品ID推理用户必须具备服务器商品向量与ID映射。

加载示例（在仓库根目录运行，需PyTorch）：
from pathlib import Path
import importlib.util
import torch
directory = Path('artifacts/models/product_three_tower_final_v1')
checkpoint = torch.load(directory / 'model.pt', map_location='cpu', weights_only=True)
spec = importlib.util.spec_from_file_location('final_model', directory / 'model_definition.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
model = module.create_model(checkpoint['config'], 763080)
model.load_state_dict(checkpoint['model'], strict=True)
model.eval()

当前CPU模型运行时：172.21.0.1:18138；推荐服务18213；网关18288。
最终Milvus别名：rs_agent_product_three_tower_final_v1_20261013。
推荐环境覆盖项：java_agent/deploy/remote/app/product-three-tower-final.env.example。
部署与验收报告：docs/reports/product-three-tower-final/RESULTS.txt。

回滚到上一服务：
ssh server /home/luo/RS_agent_remote/.venv/bin/python /mnt/data/luo/remote_runs/product_v16_final/scripts/serve_product_final.py rollback

本模型的离线数字来自已使用过的回归/复核数据；此发布没有产生新的独立效果验证。
当前服务与召回已实际验收，不据此宣称线上点击或购买转化提升。
