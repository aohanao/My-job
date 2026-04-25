import os
import subprocess
import glob
from flask import Flask, request, jsonify

app = Flask(__name__)

# 配置区域
ABAQUS_BAT_PATH = "abaqus"
SHARED_SANDBOX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "sandbox"))
print(f"[Bridge] 🚀 服务启动，SANDBOX 路径绑定为: {SHARED_SANDBOX_DIR}")

@app.route('/run_cae', methods=['POST'])
def run_cae():
    data = request.json
    script_name = data.get("script_name")
    if not script_name:
        return jsonify({"status": "error", "message": "未提供脚本名称"}), 400

    target_dir = os.path.join(SHARED_SANDBOX_DIR, "generated_scripts")
    script_path = os.path.join(target_dir, script_name)

    if not os.path.exists(script_path):
        return jsonify({"status": "error", "message": "找不到脚本"}), 404

    log_file_path = os.path.join(target_dir, f"{script_name.replace('.py', '')}.log")
    command = [ABAQUS_BAT_PATH, "cae", f"noGUI={script_name}"]

    try:
        with open(log_file_path, "w", encoding="utf-8") as log_file:
            subprocess.run(command, cwd=target_dir, stdout=log_file, stderr=subprocess.STDOUT, shell=True, timeout=300)

        with open(log_file_path, "r", encoding="utf-8") as f:
            full_output = f.read()

        if "AbaqusException" in full_output or "Error:" in full_output:
            # 🌟 [新增] 截取最后 15 行报错信息，方便远程排查
            lines = full_output.splitlines()
            error_snippet = "\n".join(lines[-15:])
            return jsonify({
                "status": "error", 
                "message": "Abaqus 内部执行报错",
                "detail": error_snippet
            }), 200

        return jsonify({"status": "success", "message": "运行成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050)
