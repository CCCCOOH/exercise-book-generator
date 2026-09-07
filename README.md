## SYNC 做题本生成器

根据pdf_maker.py一键生成做题本以供打印出来刷题，在config.ini中配置做题本的大小。
默认尺寸是A4纸大小，每张A4有两道题目，具体功能自行喂给AI解读...# exercise-book-generator

步骤：
1. 用marginnote框选你的错题并导出卡片（选择分享并保存本地）的图片集合
2. 输入为`images/`，其中存放你的marginnote保存的卡片图片集合
3. 用`uv init`初始化环境
4. 用`uv run pdf_maker.py`执行pdf生成（可在`config.ini`中配置相关配置)
5. 结果输出到`output/`下# exercise-book-generator
