import sys
import os

def setup_project_root():
    """
    动态检测并挂载项目根目录到 sys.path。
    确保无论从哪个子目录启动脚本，都能正确识别 core、integrations、skills 等顶级包。
    """
    # 获取当前文件所在目录的父目录 (即项目根目录)
    # 当前文件在 core/ 下，所以 parent 就是根目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    
    if root_dir not in sys.path:
        sys.path.append(root_dir)
        # 设置工作目录为根目录，确保相对路径的文件读写（如 .env）逻辑一致
        os.chdir(root_dir)
        
    return root_dir

# 脚本被导入时自动检查一次
setup_project_root()
