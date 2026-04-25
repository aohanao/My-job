import hashlib
import os
import re
import time
import base64
import requests
import json
import config_data as config
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from datetime import datetime

def encode_image_to_base64(image_path):
    import mimetypes
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        mime_type = "image/jpeg"
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return f"data:{mime_type};base64,{encoded_string}"

def get_image_summary(image_path: str) -> str:
    """调用阿里千问视觉模型(Qwen-VL)解析图片"""
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key: return "[未能获取大模型密钥，图片解析跳过]"
    if not os.path.exists(image_path): return "[图片本地文件丢失，解析跳过]"
    
    try:
        base64_image = encode_image_to_base64(image_path)
        payload = {
            "model": config.vlm_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "我是工程仿真专家。请提炼这张图片中最核心的工程数据或结构特征。如果是表格，提取核心参数规律。不要说废话，控制在100字以内。"},
                        {"type": "image_url", "image_url": {"url": base64_image}}
                    ]
                }
            ],
            "max_tokens": 200
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        resp = requests.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", json=payload, headers=headers, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[图片感知能力调用失败: {str(e)}]"

def get_file_md5(file_bytes: bytes) -> str:
    """计算上传文件的真实物理指纹"""
    md5_obj = hashlib.md5()
    md5_obj.update(file_bytes)
    return md5_obj.hexdigest()

def check_md5(md5_str: str) -> bool:
    """检查MD5是否已存在"""
    md5_dir = os.path.dirname(config.md5_path)
    if md5_dir:
        os.makedirs(md5_dir, exist_ok=True)
    if not os.path.exists(config.md5_path):
        open(config.md5_path, "w", encoding="utf-8").close()
        return False
    with open(config.md5_path, "r", encoding="utf-8") as f:
        return any(line.strip() == md5_str for line in f)

def save_md5(md5_str: str):
    """保存新的MD5"""
    with open(config.md5_path, "a", encoding="utf-8") as f:
        f.write(md5_str + "\n")

class KnowledgeBaseService:
    def __init__(self):
        os.makedirs(config.persist_directory, exist_ok=True)
        
        # 初始化向量模型 (使用阿里云 DashScope，配置于 config_data)
        self.embeddings = DashScopeEmbeddings(model=config.embedding_model)
        
        # 初始化 Chroma 向量库
        self.chroma = Chroma(
            collection_name=config.collection_name,
            embedding_function=self.embeddings,
            persist_directory=config.persist_directory,
        )
        
        # 🔪 武器库 1：Markdown 结构手术刀 (专治 PDF 和 MD 文件)
        headers_to_split_on = [
            ("#", "Header_H1"),
            ("##", "Header_H2"),
            ("###", "Header_H3"),
        ]
        self.md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False
        )

        # 🔪 武器库 2：字符长度切片刀 (保底防爆仓)
        self.char_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=config.separators,
        )   

    def upload_by_str(self, data: str, filename: str, file_md5: str = "", base_dir: str = "", progress_callback=None) -> str:
        """将传入的字符串（从PDF/Markdown文件提取的文本）上传到知识库中"""
        # 定义一个内部的小喇叭函数，方便调用
        def report(msg):
            if progress_callback:
                progress_callback(f"\n{msg}\n")

        # 1. 安全校验：防止空数据入库
        if not data or not data.strip():
            return f"[失败] '{filename}' 提取到的文本为空，无法上传向量库"
        
        # 判断文件后缀，决定切片策略
        file_ext = filename.split(".")[-1].lower()
        report("✂️ **1. 正在进行文档切片...**")

        # 2. 拆分文本流获取 Documents 对象
        print(f"[{filename}] 触发结构化切片管道...")
        md_docs = self.md_splitter.split_text(data)
        # 二次切分：防止某个标题下的段落超过 chunk_size
        final_docs = self.char_splitter.split_documents(md_docs)

        report(f"✅ 切片完成！共切分出 `{len(final_docs)}` 个片段")
        report("🧠 **2. 开始多模态注入与特征矩阵化...**")

        # 3. 重组 Texts 和 Metadatas，拦截包含图片链接的片段
        knowledge_chunks = []
        metadatas = []
        
        import re
        # Markdown 图片匹配正则 ![alt](path)
        img_pattern = r"!\[([^\]]*)\]\((.*?)\)"

        for i, doc in enumerate(final_docs):
            content = doc.page_content
            
            # 检测片段中是否包含图片
            image_paths_for_meta = []
            img_matches = list(re.finditer(img_pattern, content))
            
            for match in img_matches:
                img_alt = match.group(1)
                img_rel = match.group(2)
                
                # 若外部传来了基础目录，则合成绝对路径
                img_abs = os.path.normpath(os.path.join(base_dir, img_rel)) if base_dir else img_rel
                
                report(f"👁️ **多模态传感器激活**: 探测到图表 `[{img_rel}]`，正在召唤 Qwen-VL 进行视觉分析...")
                
                # 阻塞调用 VLM
                img_desc = get_image_summary(img_abs)
                
                # 将原来的图片标签替换为充满知识含量的解析文本！这部分也是后续用来 Embedding 的重点！
                replacement_text = f"\n[视觉图表分析系统: 这是一张名为'{img_alt}'的图表。核心内容提炼：{img_desc}]\n"
                content = content.replace(match.group(0), replacement_text)
                image_paths_for_meta.append(img_abs)
                
                # 防阿里防爆调用频率控制
                time.sleep(1.5)
            
            knowledge_chunks.append(content)
            
            # 继承 Markdown 切分器提取到的标题层级（如果有的话）
            meta = doc.metadata.copy() 
            # 补充我们系统的通用元数据
            meta.update({
                "source": filename,
                "file_md5": file_md5,
                "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "operator": "user",
                "chunk_index": i
            })
            if image_paths_for_meta:
                meta["image_paths"] = ";".join(image_paths_for_meta)
                
            metadatas.append(meta)

        report("📦 **3. 正在将多模态融合特征存入 Chroma...**")
        # 4. 写入 Chroma 数据库
        self.chroma.add_texts(
            texts=knowledge_chunks,
            metadatas=metadatas
        )
        report(f"✅ RAG 多模态入库完美封炉！")
        return f"[成功] '{filename}' 已深度融合为 {len(knowledge_chunks)} 个切片并入库"

    def get_all_sources(self):
        """获取所有已入库的唯一源文件名及其基本信息"""
        try:
            # 获取所有文档的元数据
            db_data = self.chroma.get()
            if not db_data or not db_data.get('metadatas'):
                return []
            
            # 按 source 分组统计
            sources = {}
            for meta in db_data['metadatas']:
                src = meta.get('source', '未知文档')
                if src not in sources:
                    sources[src] = {
                        "filename": src,
                        "chunk_count": 0,
                        "create_time": meta.get('create_time', '未知'),
                        "file_md5": meta.get('file_md5', '')
                    }
                sources[src]["chunk_count"] += 1
            
            return list(sources.values())
        except Exception as e:
            print(f"获取源文件列表失败: {e}")
            return []

    def delete_by_source(self, filename: str):
        """根据源文件名删除知识库内容及对应的 MD5 记录"""
        try:
            # 1. 查找此文件的 MD5，以便从 MD5 库中删除
            db_data = self.chroma.get(where={"source": filename}, limit=1)
            file_md5 = None
            if db_data and db_data['metadatas']:
                file_md5 = db_data['metadatas'][0].get('file_md5')

            # 2. 从 Chroma 中删除
            self.chroma.delete(where={"source": filename})
            print(f"🗑️ 已从向量库中删除文件: {filename}")

            # 3. 清理 MD5 记录，允许重新上传
            if file_md5 and os.path.exists(config.md5_path):
                with open(config.md5_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open(config.md5_path, "w", encoding="utf-8") as f:
                    for line in lines:
                        if line.strip() != file_md5:
                            f.write(line)
                print(f"🧹 已清理 MD5 记录: {file_md5}")
            
            return True
        except Exception as e:
            print(f"删除文件 {filename} 失败: {e}")
            return False


if __name__ == "__main__":
    # 测试代码
    try:
        service = KnowledgeBaseService()
        r = service.upload_by_str("这是一个集成测试字符串", "test_file.txt")
        print(r)
    except Exception as e:
        print(f"初始化或上传失败: {e}")