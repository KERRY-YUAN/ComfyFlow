# V1.5.5，未成功，参考SDPPP逻辑调整，对接comfyui节点输入输出，修改详见内容

20250416-1
@@@@@修改：“NodeBridge_Input”调整：增加模式选择，选项为“Image，Reference，Text，CN，Count”，输出格式分别对应“image，iamge，string，float，int”；

@@@@@修改：html网页端，设计工具界面，后台工作 默认加载至comfyui的工作流位置并显示comfyui工作流文件名称列表（非同目录下workflow文件夹，而是comfyui的默认workflow文件夹，如“\ComfyUI\user\default\workflows");

@@@@@修改：html网页端不再通过加载带API的workflow运行，而是直接读取当前comfyui中打开的工作流，对接其中的“NodeBridge_Input”、“NodeBridge_Output”节点;
意为：html中的“上传线稿、上传参考、文字要求、控制强度、抽卡数量”接口将分别接入“NodeBridge_Input”节点的“Image，Reference，Text，CN，Count”；
##实现以下功能，举例示意：
#当我在设计工具界面的上传线稿，上传图片后，在设计工具界面显示该图片，然后在“NodeBridge_Input”中以“Image“模式输出的节点中输出结果为该图片；
#当我上传参考，上传图片后，在设计工具界面显示该图片，然后在“NodeBridge_Input”中以“Reference“模式输出的节点中输出结果为该图片；
#当我在文字要求输入文字后，在设计工具界面显示文字，然后在“NodeBridge_Input”中以“Text“模式输出的节点中输出结果为文字；
#其他接口逻辑参考以上功能。保证“上传线稿、上传参考、文字要求、控制强度、抽卡数量、成果输出”等项均可在”设计工具界面“和comfyui中建立联系。

@@@@@修改：“NodeBridge_Input”调整：增加判定：当其可链接到html中的对应指令时，绿色显示“前端已连接”；当其无法链接到html时，红色显示“等待前端链接”

@@@@@修改：html网页端不体现（桥接 / Bridge）字样；

@@@@@修改：当前html网页端显示“等待comfyui链接”但是comfyui端口“http://127.0.0.1:8188”已经打开，html并未读取；图片上传至“上传线稿”无反应。

@@@@@修改：当修改完成，整体检查，确保launcher.py、app.py、index.html、comfyui之间运行无bug，之间链接顺畅。



20250416-2
@@@@@修改：我的comfyui运行地址端口为：http://127.0.0.1:8188/，监听comfyui端口是ws接口而不是http接口，是否有误？
@@@@@修改：当前已经可以实现在html设计工具界面读取默认的工作流，但是无法建立同comfyui之间的联系，且无法将在html设计工作界面中选择的工作流通过上传图片或文字发送至当前comfyui中运行



20250416-3
分析这个网址里的内容，并从中归纳总结其如何实现通过在PS调用comfyui中的自定义节点以实现PS和comfyui的文件链接，并对于我想要的结果，提出修改意见
@@@@@我想要的效果：
html网页端设计工具界面，直接读取当前comfyui中打开的工作流，匹配其中的“NodeBridge_Input”、“NodeBridge_Output”节点（“上传线稿、上传参考、文字要求、控制强度、抽卡数量”接口将分别接入“NodeBridge_Input”节点的“Image，Reference，Text，CN，Count”；）;
@@@@@修改：参考网址：
https://github.com/zombieyang/sd-ppp
@@@@@现app.py/launcher.py/index.html/nodebridge.py节点代码：



20250417-1
以下分别为SDPPP网址内容、设计目标、我的github网址（未包含venv文件夹）
@@@@@要求1：
分析以下SDPPP网址内容，并从中归纳借鉴，以实现通过在HTML中读取comfyui中的自定义节点内容以实现html和comfyui的交互链接，
@@@@@要求2：基本实现设计目标，在我的github仓库基础上提出修改意见

@@@@@参考的SDPPP网址：
https://github.com/zombieyang/sd-ppp
@@@@@设计目标：
html网页端设计工具界面，直接读取当前comfyui中打开的工作流，匹配其中的“NodeBridge_Input”、“NodeBridge_Output”节点（“上传线稿、上传参考、文字要求、控制强度、抽卡数量”接口将分别接入“NodeBridge_Input”节点的“Image，Reference，Text，CN，Count”；）;
#当我在设计工具界面的上传线稿，上传图片后，在设计工具界面显示该图片，然后在“NodeBridge_Input”中以“Image“模式输出的节点中输出结果为该图片；
#当我上传参考，上传图片后，在设计工具界面显示该图片，然后在“NodeBridge_Input”中以“Reference“模式输出的节点中输出结果为该图片；
#当我在文字要求输入文字后，在设计工具界面显示文字，然后在“NodeBridge_Input”中以“Text“模式输出的节点中输出结果为文字；
#其他接口逻辑参考以上功能。保证“上传线稿、上传参考、文字要求、控制强度、抽卡数量、成果输出”等项均可在”设计工具界面“和comfyui中建立联系。
@@@@@我的github网址（未包含venv文件夹）：
https://github.com/KERRY-YUAN/ComfyFlow

20250417-1-反馈：在后台加载完成后，重开前台，可连接comfyui，但是无法加载工作流，无法互动

20250417-2
基于各种原因，我的GitHub仓库中代码已更新，分析我现在的仓库各个文件代码，做出以下修改：
@@@@@要求1：
修改app.py及html文件，做到其间隔5秒就刷新下同后台端口的联系，以确保及时显示是否已连接comfyui，
@@@@@要求2：
当前状态下，运行”launcher.py“，前台html加载后，”后台工作“区域未能显示当前comfyui工作流
@@@@@要求3：
html网页端设计工具界面，直接读取当前comfyui中打开的工作流，匹配其中的“NodeBridge_Input”、“NodeBridge_Output”节点（“上传线稿、上传参考、文字要求、控制强度、抽卡数量”接口将分别接入“NodeBridge_Input”节点的“Image，Reference，Text，CN，Count”；）;
#当我在设计工具界面的上传线稿，上传图片后，在设计工具界面显示该图片，然后在“NodeBridge_Input”中以“Image“模式输出的节点中输出结果为该图片；
#当我上传参考，上传图片后，在设计工具界面显示该图片，然后在“NodeBridge_Input”中以“Reference“模式输出的节点中输出结果为该图片；
#当我在文字要求输入文字后，在设计工具界面显示文字，然后在“NodeBridge_Input”中以“Text“模式输出的节点中输出结果为文字；
#其他接口逻辑参考以上功能。保证“上传线稿、上传参考、文字要求、控制强度、抽卡数量、成果输出”等项均可在”设计工具界面“和comfyui中建立联系。
@@@@@要求4：
删除ComfyFlow目录下workflows文件夹及workflows_config.json，使得整个仓库不再从ComfyFlow目录下调用，而是直接读取当前comfyui端口打开的工作流。
@@@@@我的github仓库网址（未包含venv文件夹）：
https://github.com/KERRY-YUAN/ComfyFlow

修改计划：
删除本地工作流相关文件 (Req 4): 删除 workflows 目录和 workflows_config.json 文件。
修改 launcher.py (Req 4): 移除设置 COMFYUI_WORKFLOW_DIR 环境变量的逻辑，移除对 workflows_config.json 的检查。
修改 app.py (Req 1, 2, 3, 4):
移除加载本地工作流配置和文件的代码。
修改 / 路由，不再传递 workflow_options。
添加 /api/ping_comfyui 路由用于前端轮询 ComfyUI 状态。
修改 /api/trigger_prompt 路由：
不再接收 workflow_key。
调用 ComfyUI 的 /graph API 获取当前加载的工作流结构。
解析返回的图数据，找到 NodeBridge_Input 和 NodeBridge_Output 的节点 ID。
提取图数据中的 prompt 部分。
将前端暂存的数据 (staged_data_store) 注入到提取的 prompt 结构的 NodeBridge_Input 节点中（处理图片上传）。
调用 ComfyUI 的 /prompt API 提交修改后的 prompt。
返回 prompt_id 和找到的 output_node_id 给前端。
修改 index.html (Req 1, 2, 4):
移除“后台工作”下拉选择框 (#workflow-select 及其容器)。
调整渲染按钮 (#render-btn) 的初始状态和文本。
添加一个新的 UI 元素（例如，在页脚）用于显示轮询到的 ComfyUI 连接状态。
修改 static/js/main.js (Req 1, 2, 4):
移除与 #workflow-select 相关的代码。
修改渲染按钮的启用/禁用逻辑。
移除向 /api/trigger_prompt 发送 workflow_key 的代码。
添加 setInterval，每 5 秒调用后端的 /api/ping_comfyui，并更新 index.html 中新增的状态元素。

增加修改：
@@@@@要求1：launcher.py后端comfyui运行部分，增加判定：当后端端口页面已运行时，显示comfyui已加载并跳过后端操作，其他文件代码如有影响一并修改。
增加修改：
@@@@@要求2：
删除launcher.py对本地workflows_config.json文件的检查

20250417-2-反馈：在后台加载完成后，重开前台，可连接comfyui，但是无法加载工作流，无法互动




